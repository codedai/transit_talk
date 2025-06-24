import googlemaps
from datetime import datetime
import os
from dotenv import load_dotenv
from langchain_core.tools import tool
import requests
import re
import folium
from folium.plugins import AntPath
import polyline

from langchain_community.document_loaders import WebBaseLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain.output_parsers.structured import ResponseSchema, StructuredOutputParser
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_openai import ChatOpenAI

from go_api_simu import GoAPISimulator
from go_api import GoTrainAPI
load_dotenv()

gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

# go_api_simulator = GoAPISimulator()  # Before using it, you need to download the data from the GO Transit API and save it to the Data folder
go_api_simulator = GoTrainAPI()

# ==================================== Helper Functions ====================================
def clean_html(raw_html):
    """Remove HTML tags from HTML-formatted text."""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', raw_html)

def format_trip_text(trip):
    lines = []
    lines.append("🧭 Trip Overview")
    lines.append("======================")
    
    # Add warnings if any
    warnings = trip.get("warnings", [])
    if warnings:
        lines.append(f"Total Warnings: {len(warnings)}")
        for w in warnings:
            lines.append(f"⚠️ Warning: {w}")
    else:
        lines.append("No warnings reported.")

    # Add legs and steps
    for i, leg in enumerate(trip['legs'], start=1):
        lines.append(f"\n🚶‍♂️ Leg {i}:")
        lines.append(f"  Distance: {leg['distance']['text']}")
        lines.append(f"  Duration: {leg['duration']['text']}")
        lines.append(f"  Start: {leg['start_address']},")
        lines.append(f"  End:   {leg['end_address']},")
        lines.append("  Steps:")
        
        for j, step in enumerate(leg['steps'], start=1):
            instruction = clean_html(step['html_instructions'])
            lines.append(f"    {j}. {instruction}")
            lines.append(f"       - Mode:     {step['travel_mode']}")
            if 'transit_details' in step:
                lines.append(f"         - Agency: {step['transit_details']['line']['agencies'][0]['name']}")
            lines.append(f"       - Distance: {step['distance']['text']}")
            lines.append(f"       - Duration: {step['duration']['text']}")

    return "\n".join(lines)

def plot_trip(trip):
    """Plot the trip on a map."""
    m = folium.Map(location=[43.65107, -79.347015], zoom_start=12)
    m_name = f"route_pics/map_{datetime.now()}.html"
    for leg in trip['legs']:
        for step in leg['steps']:
            start = step['start_location']
            end = step['end_location']
            mode = step['travel_mode']
            instruction = step['html_instructions']

            if 'transit_details' in step:
                try:
                    color = step['transit_details']['line']['vehicle']['color']
                except:
                    color = 'blue'
            else:
                color = 'blue' if mode == 'WALKING' else 'green'
            
            # Add a line between start and end
            # Decode polyline points and create path
            points = polyline.decode(step['polyline']['points'])
            AntPath(locations=points,
                    color=color, delay=500).add_to(m)
            
            # Add markers for start and end
            folium.Marker(
                location=(start['lat'], start['lng']),
                popup=f"Start: {instruction}",
                icon=folium.Icon(color='blue' if mode == 'WALKING' else 'green')
            ).add_to(m)
            folium.Marker(
                location=(end['lat'], end['lng']),
                popup=f"End: {instruction}",
                icon=folium.Icon(color='gray')
            ).add_to(m)

            # save the map
            m.save(m_name)

    return m_name

# ==================================== Vector Database ====================================

web_list = [
    'https://www.gotransit.com/en/faq',
    'https://www.gotransit.com/en/travelling-on-go/dogs-travelling-on-go',
    'https://www.gotransit.com/en/travelling-on-go/travelling-with-a-stroller',
    'https://www.gotransit.com/en/your-commute-to-go/biking-and-go-transit',
    'https://www.gotransit.com/en/service-guarantee',
    'https://www.metrolinx.com/en/discover/quiet-zone-on-go-trains-now-sponsored-by-audible',
    'https://www.gotransit.com/en/travelling-on-go/wi-fi',
    'https://www.gotransit.com/en/connect-with-go',
    'https://www.gotransit.com/en/changes-at-service-counters',
    'https://www.gotransit.com/en/service-updates/where-is-my-bus',
    'https://www.gotransit.com/en/connect-with-go/go-transit-inquiries-and-feedback-process'
]

loader = WebBaseLoader(web_list)
docs = loader.load()
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
texts = text_splitter.split_documents(docs)

vectorstore = Chroma.from_documents(texts, OpenAIEmbeddings())

retriever = vectorstore.as_retriever()



# print(get_relevant_docs("What is the service guarantee?"))

# ==================================== Tools ====================================

@tool
def get_go_transit_policy_docs(query: str) -> list[Document]:
    """
    Search official GO Transit policy and support documentation.

    This tool retrieves policy or support documents relevant to a user's query, such as 
    accessibility rules, bike policies, refund procedures, or service schedules.
    Returns a list of matching documents.
    """
    return retriever.invoke(query)


# @tool
def get_route(
    origin: str,
    destination: str,
    mode: str,
    departure_time: datetime = datetime.now(),
    bounds: list[float] = None
) -> tuple[list[str], list[folium.Map]]:
    """
    Plan a public transit route between two places.

    Given an origin and destination, this tool queries the Google Maps API to 
    retrieve one or more transit routes. It returns:
    1. A list of textual route summaries (detailed, step-by-step),
    2. A list of folium maps visualizing each trip on a map.

    Mode can be set to 'transit', 'walking', or other Google Maps-supported modes.
    """
    if bounds:
        origin_result = gmaps.geocode(origin, region="CA", bounds=bounds)[0]['geometry']
        dest_result = gmaps.geocode(destination, region="CA", bounds=bounds)[0]['geometry']
    else:
        origin_result = gmaps.geocode(origin, region="CA")[0]['geometry']
        dest_result = gmaps.geocode(destination, region="CA")[0]['geometry']

    trips = gmaps.directions(
        (origin_result['location']['lat'], origin_result['location']['lng']),
        (dest_result['location']['lat'], dest_result['location']['lng']),
        mode=mode,
        departure_time=departure_time,
        alternatives=True,
        transit_routing_preference='less_walking'
    )
    
    trip_text = [format_trip_text(trip) for trip in trips]
    trip_map = [plot_trip(trip) for trip in trips]

    return trip_text, trip_map

@tool
def get_weather(
    origin: str,
    destination: str,
) -> str:
    """
    Retrieve current weather conditions for both the origin and destination.

    This tool uses the OpenWeatherMap API to fetch real-time weather data 
    (e.g., temperature and conditions) for two places identified by address or name.
    
    It is useful for informing users if they need to prepare for rain, snow, or extreme weather.
    """
    # Get coordinates for origin and destination
    origin_result = gmaps.geocode(origin, region="CA")[0]['geometry']['location']
    dest_result = gmaps.geocode(destination, region="CA")[0]['geometry']['location']

    # Get weather data from OpenWeatherMap API
    origin_weather_data = requests.get(
        f"https://api.openweathermap.org/data/3.0/onecall/overview?lat={origin_result['lat']}&lon={origin_result['lng']}&appid={os.getenv('OPEN_WHEATHER')}"
    ).json()
    
    dest_weather_data = requests.get(
        f"https://api.openweathermap.org/data/2.5/weather?lat={dest_result['lat']}&lon={dest_result['lng']}&units=metric&appid={os.getenv('OPEN_WHEATHER')}"
    ).json()

    origin_weather = f"Weather at {origin}: {origin_weather_data['weather'][0]['description']}, {origin_weather_data['main']['temp']}°C"
    dest_weather = f"Weather at {destination}: {dest_weather_data['weather'][0]['description']}, {dest_weather_data['main']['temp']}°C"

    return f"{origin_weather}\n{dest_weather}"

@tool
def get_all_go_transit_alert() -> str:
    """
    Get all real-time GO Transit alerts across the network.

    This includes service disruptions, delays, station closures, and other relevant alerts
    affecting the GO Transit system. Data is retrieved from Metrolinx’s GTFS-RT Alert feed.
    """
    base_url = "http://api.openmetrolinx.com/OpenDataAPI/"
    api_key = os.getenv("GO_TRANSIT_API_KEY")
    endpoint = "api/V1/Fleet/Occupancy/GtfsRT/Feed/Alerts"
    url = f"{base_url}{endpoint}?key={api_key}"

    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data
    else:
        return f"Error: {response.status_code}"
    
@tool
def get_go_transit_trip_updates() -> str:
    """
    Fetch real-time trip updates from GO Transit.

    Returns live vehicle arrival/departure times, delays, and other GTFS-reported
    trip-level information across the network.
    """
    base_url = "http://api.openmetrolinx.com/OpenDataAPI/"
    api_key = os.getenv("GO_TRANSIT_API_KEY")
    endpoint = "api/V1/Fleet/Occupancy/GtfsRT/Feed/TripUpdates"
    url = f"{base_url}{endpoint}?key={api_key}"

    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data
    else:
        return f"Error: {response.status_code}"
    
@tool
def get_current_time() -> str:
    """
    Return the current local system time as a formatted string.

    Useful for timestamping responses, checking departure alignment,
    or comparing with scheduled service times.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def trip_id_to_trip_od_info(trip_update_text: str) -> str:
    """
    Convert a Trip ID found in service update text into origin/destination trip info.

    This tool extracts a numeric Trip ID from the input text, queries the GO Transit API,
    and returns the corresponding origin station, origin time, destination station, and destination time
    in the format: "<Origin Station> <Departure Time> - <Destination Station> <Arrival Time>".

    Parameters:
        trip_update_text (str): A sentence or alert message containing a Trip ID (e.g., "Trip 865 is cancelled...").

    Returns:
        str: Human-readable trip segment info or an error message.
    """
    try:
        trip_id = re.findall(r'\d+', trip_update_text)[0]
        s_h = go_api_simulator.get_trip_info(trip_id)['stop_headsign']
        match = re.match(r'(.+)\s+(\d{2}:\d{2})\s+-\s+(.+)\s+(\d{2}:\d{2})', s_h)

        if match:
            origin, o_time, destination, d_time = match.groups()
            return f"{origin} {o_time} - {destination} {d_time}"
        else:
            return "Unable to parse trip origin-destination from headsign text."
    except Exception as e:
        return f"Trip ID lookup failed: {e}"


@tool
def next_available_trip(user_request: str) -> dict:
    """
    Recommend the next available GO Transit trip based on a user's request.

    This tool parses origin and destination station names from the user's request using
    a language model, converts them to GO Transit stop IDs, and retrieves the next scheduled trip.

    Parameters:
        user_request (str): A natural-language request containing trip context
                            (e.g., "What's the next train from Union to Oakville?").

    Returns:
        dict: Next available trip info (from GO API) or an error message.
    """
    # Define output schema
    trip_schema = {
        'origin': 'Origin station name',
        'destination': 'Destination station name',
    }

    schemas = [ResponseSchema(name=k, description=v) for k, v in trip_schema.items()]
    parser = StructuredOutputParser.from_response_schemas(schemas)
    format_instructions = parser.get_format_instructions()

    # Prompt to extract structured trip OD
    prompt = ChatPromptTemplate.from_messages([
        HumanMessagePromptTemplate.from_template(
            "Extract trip origin and destination from the following request.\n"
            "If either is not mentioned, return 'None'.\n"
            "{format_instructions}\n"
            "Request: {user_request}"
        )
    ]).partial(format_instructions=format_instructions)

    try:
        helper_gpt = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        response = helper_gpt(prompt.format_prompt(user_request=user_request).to_messages())
        od_dict = parser.parse(response.content)

        origin = od_dict.get("origin")
        destination = od_dict.get("destination")

        if not origin or not destination:
            return {"error": "Missing origin or destination in user request."}

        # Get stop IDs from API
        o_stop_id = go_api_simulator.get_stop_id(origin, method="embedding_search")
        d_stop_id = go_api_simulator.get_stop_id(destination, method="embedding_search")

        return go_api_simulator.get_next_available_trip(o_stop_id, d_stop_id)
    except Exception as e:
        return {"error": f"Next trip lookup failed: {e}"}
