import cv2
import time
import os
import numpy as np
import subprocess
import sys

# Paramètres
black_screen_threshold = 130  # Seuil de luminosité pour l'écran noir
max_wait_time = 180  # Timeout max en secondes pour éviter boucle infinie

# Fonction pour obtenir la version et le numéro de série
def get_os_version(ip, timeout=30):
    try:
        os_version_result = subprocess.run(
            ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'ro.build.version.incremental'],
            capture_output=True, text=True, timeout=timeout
        )
        os_version = os_version_result.stdout.strip()

        return os_version

    except subprocess.TimeoutExpired:
        print(f"La commande adb a dépassé le délai d'attente pour {ip}")
        return None
    
# Fonction pour vérifier si une frame est noire
def is_black_frame(frame, threshold=black_screen_threshold):
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg_luminance = np.mean(gray_frame)
    print(f"Luminosité moyenne : {avg_luminance}")  # Debug luminosité
    return avg_luminance < threshold

# Fonction pour attendre que la box soit de nouveau accessible après un reboot
def wait_for_device(ip, timeout=max_wait_time):
    start_time = time.time()
    print("🔄 Attente du redémarrage de la box...")

    while time.time() - start_time < timeout:
        try:
            # Vérifier si la box est en ligne
            result = subprocess.run(
                ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'sys.boot_completed'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() == "1":
                print("✅ La box est de nouveau accessible.")
                return time.time() - start_time  # Retourne le temps de reboot
        except subprocess.TimeoutExpired:
            pass
        
        print("⏳ Box toujours en cours de redémarrage...")
        time.sleep(5)

    print("❌ Erreur : La box n'est pas revenue en ligne après le timeout.")
    return None

# Fonction principale pour mesurer le temps de boot et le temps de reboot
def measure_boot_time(ip, test_type="reboot"):
    # Obtenir la version et le numéro de série
    version_info = get_os_version(ip)
    if not version_info:
        print("❌ Impossible de récupérer la version et le numéro de série.")
        return

    # Définir le chemin de sortie en fonction de la version et du numéro de série
    base_dir = f"results/{version_info}/{test_type}/"
    result_file = os.path.join(base_dir, "results.txt")
    video_source = "/dev/video0"

    # Redémarrage de la box
    print("🔄 Redémarrage de la box...")
    subprocess.run(["adb", "-s", f"{ip}:5555", "reboot"])
    time.sleep(5)

    # Attente que la box revienne en ligne et récupération du temps de reboot
    reboot_time = wait_for_device(ip)
    if reboot_time is None:
        print("❌ Abandon : La box ne s'est pas reconnectée.")
        return

    # Initialisation de la capture vidéo
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print("❌ Erreur : Impossible d'ouvrir la source vidéo.")
        return

    # Créer les répertoires nécessaires
    os.makedirs(base_dir, exist_ok=True)

    frame_width = int(cap.get(3))
    frame_height = int(cap.get(4))
    frame_rate = cap.get(cv2.CAP_PROP_FPS)

    video_filename = os.path.join(base_dir, f"capture_{int(time.time())}.mp4")
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f"{frame_width}x{frame_height}", '-r', f"{frame_rate}", '-i', '-',
        '-an', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p', video_filename
    ]
    ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    boot_start_time = time.time()
    black_screen_start = None
    print("⏳ Attente de l'écran noir...")

    timeout_start = time.time()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if is_black_frame(frame):
            if black_screen_start is None:
                black_screen_start = time.time()
        else:
            if black_screen_start:
                boot_end_time = time.time()
                boot_duration = boot_end_time - boot_start_time

                print(f"✅ Temps de boot détecté : {boot_duration:.2f} secondes")
                if ffmpeg_process:
                    ffmpeg_process.stdin.close()
                    ffmpeg_process.wait()

                # Enregistrer les résultats
                with open(result_file, 'a') as f:
                    f.write(f"{video_filename},{boot_duration:.2f},{reboot_time:.2f}\n")
                break

        if ffmpeg_process:
            ffmpeg_process.stdin.write(frame.tobytes())

        # Vérification du timeout
        if time.time() - timeout_start > max_wait_time:
            print("❌ Timeout atteint ! Fin du test.")
            break

    cap.release()
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait()

    print("✅ Test terminé.")

# Point d'entrée principal
def main(config):
    try:
        ip = config
        measure_boot_time(ip)
    except Exception as e:
        print(f"❌ Erreur : {e}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python script_reboot.py <IP>")
    else:
        main(sys.argv[1])
