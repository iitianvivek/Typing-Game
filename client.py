# client.py 
import socket
import time
import json
import threading
import sys

# --- Configuration ---
SERVER_HOST = 'localhost' # Change if server is on another machine
SERVER_PORT = 65432
BUFFER_SIZE = 1024

# --- Global State ---
client_socket = None
stop_thread = threading.Event() # Signal to stop listener thread

# --- Helper Functions ---
def send_message(sock, message_type, payload={}):
    """Sends a JSON message to the server."""
    if stop_thread.is_set(): # Don't send if we are stopping
        return
    try:
        message = json.dumps({"type": message_type, "payload": payload})
        sock.sendall(message.encode('utf-8'))
    except socket.error as e:
        print(f"\n[Error] Connection error while sending: {e}")
        stop_thread.set() # Signal stop on send error

def perform_typing_test(sentence):
    """Handles the typing input and timing. Returns typed text and time."""
    print("\n" + "="*30)
    print("Sentence to type:")
    print(f"\"{sentence}\"")
    print("="*30)
    #  Start timing immediately after printing
    print("Start typing now:")
    start_time = time.time()

    try:
        typed_text = input("> ")
    except EOFError: # Handle cases where input might be unexpectedly closed
        print("\n[Error] Input stream closed unexpectedly.")
        typed_text = "" # Assume no text typed if input fails

    end_time = time.time()
    time_taken = end_time - start_time

    print(f"\nTime taken: {time_taken:.2f} seconds. Submitting...")
    return typed_text, time_taken

# --- Server Listener Thread ---
def listen_to_server(sock):
    """Listens for messages from the server."""
    while not stop_thread.is_set():
        try:
            sock.settimeout(1.0) # Timeout to allow checking stop_thread
            data = sock.recv(BUFFER_SIZE)
            sock.settimeout(None)

            if not data:
                print("\n[Info] Server disconnected.")
                stop_thread.set()
                break

            try:
                message = json.loads(data.decode('utf-8'))
                msg_type = message.get("type")

                if msg_type == "challenge" or msg_type == "game_start":
                    sentence = message.get("sentence")
                    if sentence:
                        typed_text, time_taken = perform_typing_test(sentence)
                        # Send results back (include original sentence for server calc)
                        send_message(sock, "submit_result", {"text": typed_text, "time": time_taken, "original": sentence})
                    else:
                        print("\n[Error] Received game start/challenge without sentence.")

                elif msg_type == "game_result": # Single player result
                    results = message.get("results")
                    print("\n--- Single Player Results ---")
                    print(f"WPM: {results.get('wpm', 'N/A')}")
                    print(f"Accuracy: {results.get('accuracy', 'N/A')}%")
                    print("-----------------------------")
                    stop_thread.set() # End client after single player

                elif msg_type == "room_created":
                    room_id = message.get("room_id")
                    print(f"\n[Info] Room created! ID: {room_id}. Waiting for opponent...")

                elif msg_type == "game_over": # Multiplayer result
                    results_data = message.get("results")
                    winner = message.get("winner")
                    print("\n--- Multiplayer Game Over ---")
                    if results_data:
                        for player_addr, res in results_data.items():
                            print(f"Player {player_addr}: WPM={res.get('wpm', 'N/A')}, Acc={res.get('accuracy', 'N/A')}%")
                    print("-----------------------------")
                    print(f"Winner: {winner}")
                    print("-----------------------------")
                    stop_thread.set() # End client after multiplayer

                elif msg_type == "opponent_left":
                     print("\n[Info] Your opponent disconnected. Game over.")
                     stop_thread.set() # End client

                elif msg_type == "error":
                    error_message = message.get("message")
                    print(f"\n[ErrorFromServer] {error_message}")
                    # Decide if client should stop? For join errors, maybe not.


            except json.JSONDecodeError:
                print(f"\n[Warning] Received non-JSON data: {data.decode('utf-8', errors='ignore')}")
            except Exception as e:
                 print(f"\n[Error] Error processing server message: {e}")

        except socket.timeout:
            continue # Normal timeout, check stop_thread and loop
        except socket.error as e:
            if not stop_thread.is_set():
                 print(f"\n[Error] Connection error: {e}")
            stop_thread.set() # Stop on socket error
            break
        except Exception as e:
            print(f"\n[Error] Unexpected error in listener: {e}")
            stop_thread.set()
            break

    print("[Info] Listener stopped.")
    # Ensure socket is closed if thread stops unexpectedly
    global client_socket
    if client_socket:
        try:
            client_socket.close()
        except socket.error:
            pass


# --- Main Client Logic ---
def main():
    global client_socket
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"Connecting to {SERVER_HOST}:{SERVER_PORT}...")
        client_socket.connect((SERVER_HOST, SERVER_PORT))
        print("Connected!")

        listener_thread = threading.Thread(target=listen_to_server, args=(client_socket,), daemon=True)
        listener_thread.start()

        # --- Mode Selection ---
        mode_selected = False
        while not stop_thread.is_set() and not mode_selected:
            print("\nChoose mode:")
            print("1. Single Player")
            print("2. Multiplayer")
            choice = input("Enter choice: ")

            if choice == '1':
                send_message(client_socket, "choose_mode", {"mode": "single"})
                mode_selected = True # Wait for server challenge
            elif choice == '2':
                send_message(client_socket, "choose_mode", {"mode": "multiplayer"})
                # --- Multiplayer Action ---
                action_selected = False
                while not stop_thread.is_set() and not action_selected:
                    print("\nMultiplayer:")
                    print("1. Create Room")
                    print("2. Join Room")
                    mp_choice = input("Enter choice: ")
                    if mp_choice == '1':
                        send_message(client_socket, "multiplayer_action", {"action": "create"})
                        action_selected = True
                        mode_selected = True # Now wait for opponent or game start
                    elif mp_choice == '2':
                        room_id = input("Enter Room ID: ")
                        # Basic validation: check if it's not empty
                        if room_id:
                             send_message(client_socket, "multiplayer_action", {"action": "join", "room_id": room_id})
                             action_selected = True
                             mode_selected = True # Now wait for game start or error
                        else:
                             print("Invalid Room ID.")
                    else:
                         print("Invalid choice.")
            else:
                print("Invalid choice.")

        # Keep main thread alive while listener is running
        while not stop_thread.is_set():
            try:
                time.sleep(1) # Just wait
            except KeyboardInterrupt:
                 print("\n[Info] Ctrl+C detected. Closing...")
                 stop_thread.set()
                 break

    except socket.error as e:
        print(f"[Error] Cannot connect to server: {e}")
    except Exception as e:
        print(f"[Error] An unexpected error occurred: {e}")
    finally:
        stop_thread.set() # Signal listener to stop
        if client_socket:
            try:
                client_socket.close()
            except socket.error:
                pass # Ignore errors during cleanup
        print("Client finished.")
        # Wait briefly for listener thread to potentially exit
        time.sleep(0.5)


if __name__ == "__main__":
    main()
