import os
import ast
import datetime
import pandas as pd
import numpy as np
from math import radians, sin, cos, sqrt, atan2
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer


# ========================== Tools ==========================

def read_from_file(folder_path: str):
    """
    Load L101.csv, L102.csv, and DelayCodeInfo.csv from the given folder.

    Returns:
        Tuple of (l101_df, l102_df, delay_code_info_df)
    """
    l101_path = os.path.join(folder_path, "L101.csv")
    l102_path = os.path.join(folder_path, "L102.csv")
    delay_code_path = os.path.join(folder_path, "DelayCodeInfo.csv")

    l101_df = pd.read_csv(l101_path, parse_dates=['OperationDateTime'])
    l102_df = pd.read_csv(l102_path)
    delay_code_info_df = pd.read_csv(delay_code_path)

    return l101_df, l102_df, delay_code_info_df

def merge_data(l101_df: pd.DataFrame, l102_df: pd.DataFrame, delay_code_info_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge L101 and L102 tables on common keys (e.g., TripId), then attach DelayCode info.

    Returns:
        Cleaned and merged DataFrame ready for delay analysis.
    """
    # Merge L101 and L102 by 'TripId' or other shared identifier
    merged = pd.merge(l101_df, l102_df, on='TripId', how='left')

    # Merge delay codes into the result (e.g., on DelayCode column)
    merged = pd.merge(merged, delay_code_info_df, on='DelayCode', how='left')

    return merged

# ========================== GoAPISimulator ==========================

class GoAPISimulator:
    def __init__(self, data_dir="Data/gtfs-2018", start_date=20180301, end_date=20180308, corridor='LE'):
        """
        Initialize and load GTFS data, stop embeddings, and delay logs.
        """
        # Load GTFS data
        calendar_dates = pd.read_csv(os.path.join(data_dir, "calendar_dates.txt"))
        trips = pd.read_csv(os.path.join(data_dir, "trips.txt"))
        stop_times = pd.read_csv(os.path.join(data_dir, "stop_times.txt"))

        self.stops = pd.read_csv(os.path.join(data_dir, "stops.csv"))
        self.stops['embedding'] = self.stops['embedding'].apply(ast.literal_eval)

        self.embedding_model = SentenceTransformer('sentence-transformers/all-roberta-large-v1')

        # Filter by valid service dates and corridor
        service_ids = calendar_dates[
            (calendar_dates.service_id >= start_date) &
            (calendar_dates.service_id <= end_date)
        ].service_id.tolist()

        valid_trips = trips[
            trips.service_id.isin(service_ids) & trips.route_id.str.endswith(corridor)
        ]

        self.stop_time_clean = stop_times[
            stop_times.trip_id.isin(valid_trips.trip_id.unique())
        ]

        # Load and filter delay logs
        l101_df, l102_df, delay_code_info_df = read_from_file('Data/L101 and L102 - 2018')
        delay_logs = merge_data(l101_df, l102_df, delay_code_info_df)

        self.delay_logs_clean_df = delay_logs[
            (delay_logs.OperationDateTime.dt.date >= datetime.date(2018, 3, 1)) &
            (delay_logs.OperationDateTime.dt.date <= datetime.date(2018, 3, 8)) &
            (delay_logs.CorridorId == corridor) &
            (delay_logs.DelayCode.notnull())
        ].sort_values(by='OperationDateTime')

    # ========================== Control Log ==========================

    def get_control_log(self) -> dict:
        """Return one random delay log as a dict."""
        return self.delay_logs_clean_df.sample(1).to_dict(orient='records')[0]

    # ========================== Trip Info ============================

    def get_trip_info(self, trip_id: str, date='20180301', corridor='LE') -> dict:
        """
        Retrieve full trip info, including all stop times and OD summary.

        Args:
            trip_id: numeric or string trip ID (without GTFS prefix).
            date: GTFS service date string, e.g., '20180301'.
            corridor: route corridor identifier (e.g., 'LE').

        Returns:
            Dictionary with origin, destination, stop times, and trip summary.
        """
        full_trip_id = f"{date}-{corridor}-{trip_id}"
        trip_data = self.stop_time_clean[
            self.stop_time_clean.trip_id == full_trip_id
        ].merge(self.stops, on='stop_id')

        if trip_data.empty:
            raise ValueError(f"Trip ID {full_trip_id} not found.")

        try:
            headsign = trip_data[trip_data.stop_sequence == trip_data.stop_sequence.min()].stop_headsign.values[0]
        except IndexError:
            raise ValueError(f"Missing stop_headsign for trip {trip_id}.")

        stop_sequence = [
            {
                'stop_sequence': seq,
                'stop_name': row.stop_name,
                'arrival_time': row.arrival_time,
                'departure_time': row.departure_time,
            }
            for seq, row in trip_data.groupby('stop_sequence').first().iterrows()
        ]

        return {
            'trip_id': full_trip_id,
            'stop_headsign': headsign,
            'origin': trip_data.iloc[0].stop_name,
            'destination': trip_data.iloc[-1].stop_name,
            'departure_time': trip_data.iloc[0].departure_time,
            'arrival_time': trip_data.iloc[-1].arrival_time,
            'stop_sequence': stop_sequence,
        }

    # ========================== Stop ID Lookup ==========================

    def get_stop_id(self, stop_name=None, lat=None, long=None, method=None) -> str:
        """
        Return stop_id using either name match, semantic embedding match, or geo distance.

        Args:
            stop_name: name of the station/stop.
            lat, long: coordinates if using geo search.
            method: one of None, 'embedding_search', 'geo_search'.

        Returns:
            stop_id (str)
        """
        try:
            if method is None:
                return self.stops[self.stops.stop_name == stop_name].stop_id.values[0]

            elif method == 'embedding_search':
                if stop_name is None:
                    raise ValueError("stop_name is required for embedding search")
                input_emb = self.embedding_model.encode(stop_name)
                sim_scores = self.stops.embedding.apply(
                    lambda x: self.calculate_cosine_similarity(input_emb, x)
                )
                return self.stops.iloc[sim_scores.idxmax()].stop_id

            elif method == 'geo_search':
                if lat is None or long is None:
                    raise ValueError("Both lat and long are required for geo search")
                dist_scores = self.stops.apply(
                    lambda row: self.calculate_distance(lat, long, row.stop_lat, row.stop_lon),
                    axis=1
                )
                return self.stops.iloc[dist_scores.idxmin()].stop_id

        except IndexError:
            raise ValueError(f"Stop not found using method: {method}")

    # ========================== Next Trip ==========================

    def get_next_available_trip(self, o_stop_id: str, d_stop_id: str, time=None) -> dict:
        """
        Dummy lookup for next available trip between two stops.

        (Currently hardcoded — replace with real-time logic if needed.)
        """
        return {
            'trip_id': '907',
            'origin': 'Oshawa GO',
            'destination': 'Union Station',
            'departure_time': '07:42:00',
            'arrival_time': '08:45:00',
        }

    # ========================== Station Alerts ==========================

    def get_station_alert(self, stop_id: str) -> str:
        """
        Return station-level alert information.

        Args:
            stop_id: stop identifier from GTFS.

        Returns:
            string describing construction or delay notice.
        """
        return (
            "🚧 Station Alert:\n"
            "Starting Monday, June 19, new traffic signals will be installed at Dissette St. "
            "and the driveway to Bradford GO. Lane restrictions between 9 AM–3 PM daily. "
            "Staff will guide traffic. Completion expected in July.\n"
            "Please follow signs and be cautious. 🚦"
        )

    # ========================== Utils ==========================

    @staticmethod
    def calculate_cosine_similarity(vec1, vec2) -> float:
        """Compute cosine similarity between two vectors."""
        v1 = np.array(vec1).reshape(1, -1)
        v2 = np.array(vec2).reshape(1, -1)
        return cosine_similarity(v1, v2)[0, 0]

    @staticmethod
    def calculate_distance(lat1, lon1, lat2, lon2) -> float:
        """Compute Haversine distance (in km) between two lat/lon points."""
        r = 6371.0  # Earth radius in km
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        return r * 2 * atan2(sqrt(a), sqrt(1 - a))


# ========================== Dev Testing ==========================
if __name__ == '__main__':
    sim = GoAPISimulator()
    print(sim.get_trip_info('703'))
    print(sim.get_control_log())
