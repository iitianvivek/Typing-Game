# server.py (updated)
import socket
import threading

clients = {} 

def broadcast(message, sender_socket=None):
    """Send a message to all clients except the sender."""
    for client_socket in clients:
        if client_socket != sender_socket:
            try:
                client_socket.send(message.encode('utf-8'))
            except:
                # Remove disconnected clients
                del clients[client_socket]
                client_socket.close()

def handle_client(client_socket, addr):
    username = client_socket.recv(1024).decode('utf-8')
    clients[client_socket] = username
    print(f"[NEW CONNECTION] {addr} -> {username}")
    broadcast(f"[SERVER] {username} joined!", sender_socket=client_socket)

    while True:
        try:
            message = client_socket.recv(1024).decode('utf-8')
            if not message:
                break
            print(f"[{username}] {message}")
            broadcast(f"[{username}] {message}", sender_socket=client_socket)
        except:
            break

    # On disconnect
    broadcast(f"[SERVER] {username} left!", sender_socket=client_socket)
    del clients[client_socket]
    client_socket.close()
    print(f"[DISCONNECTED] {username}")

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', 5555))
    server.listen()
    print("[SERVER] Listening on port 5555...")

    while True:
        client_socket, addr = server.accept()
        thread = threading.Thread(target=handle_client, args=(client_socket, addr))
        thread.start()

if __name__ == "__main__":
    start_server()