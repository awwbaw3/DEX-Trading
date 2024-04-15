import json
import requests

def fetch_token_details(token_address):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching token details for {token_address}: {e}")
        return None

def process_new_tokens_log(file_path):
    try:
        with open(file_path, 'r') as file:
            token_data_results = []
            for line in file:
                token_data = json.loads(line)
                token_address = token_data["token"]
                result = fetch_token_details(token_address)
                if result:
                    token_data_results.append(result)
            return token_data_results
    except FileNotFoundError:
        print(f"The file {file_path} does not exist.")
        return []

def save_results_to_file(results, output_file):
    with open(output_file, 'w') as file:
        json.dump(results, file, indent=4)

if __name__ == "__main__":
    input_log_file = "new_tokens.log"
    output_file = "new_tokens_dexscreener.log"
    # Clear the output file at the beginning of the script to ensure it starts fresh
    with open(output_file, 'w') as clear_file:
        pass
    results = process_new_tokens_log(input_log_file)
    save_results_to_file(results, output_file)
    print(f"Results have been saved to {output_file}.")