import requests
import os


class GoTrainAPI:
    def __init__(self, base_url="http://api.openmetrolinx.com/OpenDataAPI/"):
        self.base_url = base_url
        self.api_key = os.environ.get('GO_API_KEY')

    def get_next_service(self, stop_code):
        endpoint = f"api/V1/Stop/NextService/{stop_code}"
        return self._make_request(endpoint)

    def get_details(self, stop_code):
        endpoint = f"api/V1/Stop/Details/{stop_code}"
        return self._make_request(endpoint)

    def get_destinations(self, stop_code, from_time, to_time):
        endpoint = f"api/V1/Stop/Destinations/{stop_code}/{from_time}/{to_time}"
        return self._make_request(endpoint)

    def get_all_stops(self):
        endpoint = "api/V1/Stop/All"
        return self._make_request(endpoint)

    def get_service_alerts(self):
        endpoint = "api/V1/ServiceUpdate/ServiceAlert/All"
        return self._make_request(endpoint)

    def get_information_alerts(self):
        endpoint = "api/V1/ServiceUpdate/InformationAlert/All"
        return self._make_request(endpoint)

    def get_marketing_alerts(self):
        endpoint = "api/V1/ServiceUpdate/MarketingAlert/All"
        return self._make_request(endpoint)

    def get_union_departures(self):
        endpoint = "api/V1/ServiceUpdate/UnionDepartures/All"
        return self._make_request(endpoint)

    def get_service_guarantee(self, trip_number, operational_day):
        endpoint = f"api/V1/ServiceUpdate/ServiceGuarantee/{trip_number}/{operational_day}"
        return self._make_request(endpoint)

    def get_train_exceptions(self):
        endpoint = "api/V1/ServiceUpdate/Exceptions/Train"
        return self._make_request(endpoint)

    def get_bus_exceptions(self):
        endpoint = "api/V1/ServiceUpdate/Exceptions/Bus"
        return self._make_request(endpoint)

    def get_all_exceptions(self):
        endpoint = "api/V1/ServiceUpdate/Exceptions/All"
        return self._make_request(endpoint)

    def get_journey_schedule(self, date, from_stop_code, to_stop_code, start_time, max_journey):
        endpoint = f"api/V1/Schedule/Journey/{date}/{from_stop_code}/{to_stop_code}/{start_time}/{max_journey}"

        return self._make_request(endpoint)

    def get_line_schedule(self, date, line_code, line_direction):
        endpoint = f"api/V1/Schedule/Line/{date}/{line_code}/{line_direction}"
        return self._make_request(endpoint)

    def get_all_lines_schedule(self, date):
        endpoint = f"api/V1/Schedule/Line/All/{date}"
        return self._make_request(endpoint)

    def get_line_stops_schedule(self, date, line_code, line_direction):
        endpoint = f"api/V1/Schedule/Line/Stop/{date}/{line_code}/{line_direction}"
        return self._make_request(endpoint)

    def get_trip_schedule(self, date, trip_number):
        endpoint = f"api/V1/Schedule/Trip/{date}/{trip_number}"
        return self._make_request(endpoint)

    def get_all_bus_trips(self):
        endpoint = f"api/V1/ServiceataGlance/Buses/All"
        return self._make_request(endpoint)

    def get_all_train_trips(self):
        endpoint = f"api/V1/ServiceataGlance/Trains/All"
        return self._make_request(endpoint)

    def get_all_upx_trips(self):
        endpoint = f"api/V1/ServiceataGlance/UPX/All"
        return self._make_request(endpoint)

    def _make_request(self, endpoint):
        url = self.base_url + endpoint + "?key=" + self.api_key
        response = requests.get(url)

        if response.status_code == 200:
            return response.json()
        else:
            return None  # or handle the error case accordingly


