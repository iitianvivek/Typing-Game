# server.py 
import socket
import threading
import random
import time
import json

# --- Configuration ---
HOST = '0.0.0.0'
PORT = 65432
BUFFER_SIZE = 1024
SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "Practice makes perfect.",
    "Keep your friends close.",
    "Simplicity is key.",
    "Hello world example."
]

# --- Server State ---
clients = {} # {conn: {"addr": addr, "room_id": None}}
rooms = {}   # {room_id: {"players": [conn1, conn2], "sentence": None, "results": {conn1: None, conn2: None}, "status": "waiting"}}

# --- Helper Functions ---
def generate_room_id():
    """Generates a simple unique room ID."""
    while True:
        room_id = str(random.randint(1000, 9999))
        if room_id not in rooms:
            return room_id

def calculate_results(original_sentence, typed_text, time_taken):
    """Calculates WPM and Accuracy."""
    if not original_sentence or time_taken <= 0:
        return {"wpm": 0, "accuracy": 0.0}

    typed_words = typed_text.split()
    word_count = len(typed_words)
    wpm = int((word_count / time_taken) * 60) if time_taken > 0 else 0

    correct_chars = 0
    min_len = min(len(original_sentence), len(typed_text))
    for i in range(min_len):
        if original_sentence[i] == typed_text[i]:
            correct_chars += 1
    accuracy = (correct_chars / len(original_sentence)) * 100 if len(original_sentence) > 0 else 0.0

    return {"wpm": wpm, "accuracy": round(accuracy, 2)}

def cleanup_client(conn):
    """Removes client data and cleans up their room if necessary."""
    print(f"[DISCONNECT] Client {clients.get(conn, {}).get('addr')} disconnected.")
    if conn in clients:
        room_id = clients[conn].get("room_id")
        if room_id and room_id in rooms:
            print(f"[ROOM] Removing room {room_id} due to player disconnect.")
            # Notify other player if they exist
            other_player = None
            if room_id in rooms: # Check if room still exists
                for player_conn in rooms[room_id]["players"]:
                    if player_conn != conn and player_conn in clients: # Make sure other player still connected
                         other_player = player_conn
                         break
                if other_player:
                    try:
                        other_player.sendall(json.dumps({"type": "opponent_left"}).encode('utf-8'))
                    except socket.error:
                        print(f"[WARN] Could not notify other player in room {room_id} about disconnect.")

                del rooms[room_id] # Delete the room

        del clients[conn] # Remove client from main list
    try:
        conn.close()
    except socket.error:
        pass # Ignore errors on closing

# --- Client Handling Logic ---
def handle_client(conn, addr):
    """Handles communication with a single client."""
    print(f"[CONNECT] New connection from {addr}")
    clients[conn] = {"addr": addr, "room_id": None}
    current_state = "connected" 

    try:
        while True:
            data = conn.recv(BUFFER_SIZE)
            if not data:
                break # Connection closed

            try:
                message = json.loads(data.decode('utf-8'))
                print(f"[RECV] From {addr}: {message}")
                msg_type = message.get("type")
                payload = message.get("payload", {})

                # --- Mode Selection ---
                if current_state == "connected" and msg_type == "choose_mode":
                    mode = payload.get("mode")
                    if mode == "single":
                        current_state = "single_player"
                        sentence = random.choice(SENTENCES)
                        conn.sendall(json.dumps({"type": "challenge", "sentence": sentence}).encode('utf-8'))
                    elif mode == "multiplayer":
                        current_state = "multiplayer_menu"
                        
                    else:
                         conn.sendall(json.dumps({"type": "error", "message": "Invalid mode."}).encode('utf-8'))

                # --- Single Player Result ---
                elif current_state == "single_player" and msg_type == "submit_result":
                    typed_text = payload.get("text", "")
                    time_taken = payload.get("time", 0)
                    original_sentence = payload.get("original", "")
                    results = calculate_results(original_sentence, typed_text, time_taken)
                    conn.sendall(json.dumps({"type": "game_result", "results": results}).encode('utf-8'))
                    break # End single player session

                # --- Multiplayer Actions ---
                elif current_state == "multiplayer_menu" and msg_type == "multiplayer_action":
                    action = payload.get("action")
                    if action == "create":
                        room_id = generate_room_id()
                        rooms[room_id] = {"players": [conn], "sentence": None, "results": {conn: None}, "status": "waiting"}
                        clients[conn]["room_id"] = room_id
                        current_state = "in_room_waiting"
                        conn.sendall(json.dumps({"type": "room_created", "room_id": room_id}).encode('utf-8'))
                        print(f"[ROOM] Client {addr} created room {room_id}")
                    elif action == "join":
                        room_id = payload.get("room_id")
                        if room_id in rooms and rooms[room_id]["status"] == "waiting" and len(rooms[room_id]["players"]) == 1:
                            # Join the room
                            clients[conn]["room_id"] = room_id
                            rooms[room_id]["players"].append(conn)
                            rooms[room_id]["results"][conn] = None # Add player result slot
                            rooms[room_id]["status"] = "playing"
                            current_state = "in_room_playing" # Update state for joining player

                            # Start game for both
                            sentence = random.choice(SENTENCES)
                            rooms[room_id]["sentence"] = sentence
                            start_message = json.dumps({"type": "game_start", "sentence": sentence}).encode('utf-8')

                            # Update state for the waiting player too
                            waiting_player_conn = rooms[room_id]["players"][0]
                            # Find the handle_client thread for the waiting player is hard,
                            # so we rely on the client receiving game_start to know it's playing.

                            for player_conn in rooms[room_id]["players"]:
                                player_conn.sendall(start_message)
                            print(f"[ROOM] Client {addr} joined room {room_id}. Game starting.")
                        else:
                            conn.sendall(json.dumps({"type": "error", "message": f"Cannot join room {room_id} (Not found, full, or already playing)."}).encode('utf-8'))
                            # Keep state as multiplayer_menu to allow retry
                    else:
                        conn.sendall(json.dumps({"type": "error", "message": "Invalid multiplayer action."}).encode('utf-8'))

                # --- Multiplayer Game Result Submission ---
                # This state check assumes the client knows it's playing after receiving game_start
                elif msg_type == "submit_result": 
                    room_id = clients[conn].get("room_id")
                    if room_id and room_id in rooms and rooms[room_id]["status"] == "playing":
                        # Check if this player already submitted (basic prevention)
                        if conn in rooms[room_id]["results"] and rooms[room_id]["results"][conn] is not None:
                            print(f"[WARN] Player {addr} tried to submit results twice for room {room_id}.")
                            continue # Ignore second submission

                        typed_text = payload.get("text", "")
                        time_taken = payload.get("time", 0)
                        original_sentence = rooms[room_id]["sentence"] # Get sentence from room
                        results = calculate_results(original_sentence, typed_text, time_taken)
                        rooms[room_id]["results"][conn] = results # Store result
                        print(f"[GAME] Received results from {addr} in room {room_id}")

                        # Check if all results are in
                        all_results_in = all(res is not None for res in rooms[room_id]["results"].values())
                        if all_results_in and len(rooms[room_id]["players"]) == 2:
                            rooms[room_id]["status"] = "finished" # Mark room as finished internally
                            player_conns = rooms[room_id]["players"]
                            results1 = rooms[room_id]["results"][player_conns[0]]
                            results2 = rooms[room_id]["results"][player_conns[1]]

                            # Determine winner (simple WPM comparison)
                            winner_addr_str = "Draw"
                            if results1["wpm"] > results2["wpm"]:
                                winner_addr_str = str(clients[player_conns[0]]["addr"])
                            elif results2["wpm"] > results1["wpm"]:
                                winner_addr_str = str(clients[player_conns[1]]["addr"])
                            # Ignoring accuracy tie-breaker for simplicity

                            print(f"[GAME] Room {room_id} finished. Winner: {winner_addr_str}")

                            # Prepare results message
                            final_results_payload = {
                                str(clients[p]["addr"]): rooms[room_id]["results"][p] for p in player_conns
                            }
                            final_message = json.dumps({
                                "type": "game_over",
                                "results": final_results_payload,
                                "winner": winner_addr_str
                            }).encode('utf-8')

                            # Send to both players
                            for p_conn in player_conns:
                                try:
                                    p_conn.sendall(final_message)
                                except socket.error:
                                    print(f"[WARN] Could not send final results to a player in room {room_id}.")
                            # Room will be cleaned up when players disconnect

                        elif not all_results_in:
                             pass

                    else:
                        print(f"[WARN] Received result from {addr} but not in a valid playing room.")

                else:
                    print(f"[WARN] Unhandled message type '{msg_type}' or state '{current_state}' from {addr}")


            except json.JSONDecodeError:
                print(f"[ERROR] Invalid JSON received from {addr}")
            except Exception as e:
                 print(f"[ERROR] Error processing message from {addr}: {e}")
                 # Basic error feedback
                 try:
                     conn.sendall(json.dumps({"type": "error", "message": "Server error occurred."}).encode('utf-8'))
                 except socket.error:
                     pass # Client might be disconnected

    except socket.error as e:
        print(f"[ERROR] Socket error with client {addr}: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error with client {addr}: {e}")
    finally:
        cleanup_client(conn) # Ensure cleanup happens

# --- Main Server Execution ---
def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        print(f"[INFO] Simplified Server listening on {HOST}:{PORT}")

        while True:
            conn, addr = server_socket.accept()
            client_thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            client_thread.start()

    except socket.error as e:
        print(f"[FATAL] Socket error on startup: {e}")
    except KeyboardInterrupt:
        print("\n[INFO] Server shutting down.")
    finally:
        print("[INFO] Closing server socket.")
        
        server_socket.close()

if __name__ == "__main__":
    start_server()
