import json
import os
import time
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configuration
input_file = 'history.ndjson'
victoriametrics_url = 'http://localhost:8428/api/v1/import'

# Track processed lines to avoid duplication
processed_lines = set()

def convert_to_victoriametrics_format(new_lines):
    timeseries = {}

    for line in new_lines:
        try:
            data = json.loads(line)

            metric_name = data['name']
            timestamp = data['clock'] * 1000 + data['ns'] / 1e6  # Convert to milliseconds
            value = data['value']

            labels = {tag['tag']: tag['value'] for tag in data['item_tags']}
            labels['itemid'] = data['itemid']
            labels['host'] = data['host']['host']
            labels['group'] = data['groups'][0] if data['groups'] else 'unknown'
            key = json.dumps(labels, sort_keys=True)

            if key not in timeseries:
                timeseries[key] = {
                    "metric": {"__name__": metric_name, **labels},
                    "values": [],
                    "timestamps": []
                }

            timeseries[key]["values"].append(value)
            timeseries[key]["timestamps"].append(int(timestamp))
        except json.JSONDecodeError as e:
            print(f"Failed to parse line: {line}")
            print(f"Error: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

    return timeseries
def push_to_victoriametrics(timeseries):
    for ts in timeseries.values():
        # Prepare the payload for VictoriaMetrics
        payload = {
            "metric": ts["metric"],
            "values": ts["values"],
            "timestamps": ts["timestamps"]
        }

        try:
            # Send data to VictoriaMetrics
            response = requests.post(victoriametrics_url, json=payload)
            response.raise_for_status()
            print(f"Successfully pushed {len(ts['values'])} records to VictoriaMetrics.")
        except requests.exceptions.RequestException as e:
            print(f"Failed to push records: {e}")



class LogFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith(input_file):
            print(f"Detected modification in {input_file}")

            # Read new lines
            with open(input_file, 'r') as file:
                lines = file.readlines()
                new_lines = [line for line in lines if line not in processed_lines]

                # Update processed lines
                processed_lines.update(new_lines)

                # Convert and push new data
                if new_lines:
                    print(f"Processing {len(new_lines)} new lines...")
                    timeseries = convert_to_victoriametrics_format(new_lines)
                    push_to_victoriametrics(timeseries)
                else:
                    print("No new lines to process.")

if __name__ == "__main__":
    print("Starting the log file handler...")

    # Initial processing of existing lines
    if os.path.exists(input_file):
        with open(input_file, 'r') as file:
            lines = file.readlines()
            if lines:
                print(f"Processing {len(lines)} lines from the existing file...")
                processed_lines.update(lines)
                timeseries = convert_to_victoriametrics_format(lines)
                push_to_victoriametrics(timeseries)
            else:
                print("Input file is empty.")
    else:
        print(f"File {input_file} does not exist.")

    event_handler = LogFileHandler()
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("Stopping the observer...")

    observer.join()
