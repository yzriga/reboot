import cv2
import time
import os
import numpy as np
import subprocess
import sys
import importlib.util

# Paramètres
black_screen_threshold = 20  # Ajuster en fonction des valeurs de l’écran noir
max_wait_time = 180  # Timeout max pour éviter boucle infinie
result_base_dir = "/home/bytel/IVS/results/KPI/"  # Définition en dur du chemin de stockage des résultats

# Fonction pour vérifier si une frame est noire
def is_black_frame(frame, threshold=black_screen_threshold):
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg_luminance = np.mean(gray_frame)
    print(f"Luminosité moyenne : {avg_luminance}")  # Debug luminosité
    return avg_luminance < threshold

# Fonction pour récupérer uniquement la version de l'OS
def get_os_version(ip, timeout=30):
    try:
        os_version_result = subprocess.run(
            ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'ro.build.version.incremental'],
            capture_output=True, text=True, timeout=timeout
        )
        os_version = os_version_result.stdout.strip()
        return os_version  # Ne retourne que la version, pas le numéro de série
    except subprocess.TimeoutExpired:
        print(f"Erreur : Timeout lors de la récupération de la version pour {ip}")
        return "unknown_version"

# Fonction pour attendre que la box soit de nouveau accessible après un reboot
def wait_for_device(ip, timeout=max_wait_time):
    start_time = time.time()
    print("Attente du redémarrage de la box...")

    while time.time() - start_time < timeout:
        try:
            result = subprocess.run(
                ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'sys.boot_completed'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip() == "1":
                print("La box est de nouveau accessible.")
                return time.time() - start_time  # Retourne le temps de reboot
        except subprocess.TimeoutExpired:
            pass
        
        print("Box toujours en cours de redémarrage...")
        time.sleep(5)

    print("Erreur : La box n'est pas revenue en ligne après le timeout.")
    return None

# Fonction principale pour mesurer le temps de boot et capturer la vidéo
def measure_boot_time(ip, video_source, log_dir):
    # Récupération de la version de l'OS
    os_version = get_os_version(ip)

    # Définition du chemin de stockage (Comme dans la version 2)
    base_dir = os.path.join(result_base_dir, os_version, "reboot")
    if not os.path.exists(base_dir):
        os.makedirs(base_dir, exist_ok=True)

    result_file = os.path.join(base_dir, "results.txt")
    log_file = os.path.join(log_dir, "script_reboot.log")

    # Vérifier que results.txt existe
    if not os.path.exists(result_file):
        open(result_file, 'w').close()

    # Enregistrer les logs
    with open(log_file, "a") as log:
        log.write(f"Début du test avec IP: {ip}, Source vidéo: {video_source}\n")

    # Redémarrage de la box
    print("Redémarrage de la box...")
    subprocess.run(["adb", "-s", f"{ip}:5555", "reboot"])
    time.sleep(5)

    # Attente du reboot et récupération du temps de reboot
    reboot_time = wait_for_device(ip)
    if reboot_time is None:
        print("Abandon : La box ne s'est pas reconnectée.")
        return

    # Initialisation de la capture vidéo
    print(f"Utilisation de la source vidéo : {video_source}")
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"Erreur : Impossible d'ouvrir la source vidéo {video_source}.")
        return

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
    print("Attente de l'écran noir...")

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

                print(f"Temps de boot détecté : {boot_duration:.2f} secondes")
                if ffmpeg_process:
                    ffmpeg_process.stdin.close()
                    ffmpeg_process.wait()

                # Écriture des résultats dans le fichier avec "Temps de boot" et "Temps de reboot"
                with open(result_file, 'a') as f:
                    f.write(f"{video_filename},{boot_duration:.2f}\n")

                # Écrire dans les logs
                with open(log_file, "a") as log:
                    log.write(f"Temps de boot détecté : {boot_duration:.2f} secondes\n")

                break

        if ffmpeg_process:
            ffmpeg_process.stdin.write(frame.tobytes())

        # Vérification du timeout
        if time.time() - timeout_start > max_wait_time:
            print("Timeout atteint ! Fin du test.")

            # Si aucun boot_time détecté, écrire un échec dans results.txt
            with open(result_file, 'a') as f:
                f.write(f"{video_filename},BOOT TIMEOUT\n")

            break

    cap.release()
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait()

    print("Test terminé.")
    if os.path.exists(result_file):
        print(f"Résultats enregistrés dans : {result_file}")
    else:
        print("Erreur : Le fichier de résultats n'a pas été généré.")

    with open(log_file, "a") as log:
        log.write("Test terminé.\n")

# Fonction pour charger dynamiquement le fichier de configuration
def load_config(config_path):
    if not os.path.isfile(config_path):
        print(f"[ERREUR] Le fichier de configuration {config_path} n'existe pas.")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("config", config_path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config

# Point d'entrée principal
def main(config, log_dir):
    try:
        ip = config.IP  
        video_source = config.hdmi  

        if not video_source:
            print("[ERREUR] Aucune source vidéo définie dans le fichier de configuration.")
            sys.exit(1)

        # Vérifier et créer log_dir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        measure_boot_time(ip, video_source, log_dir)

    except Exception as e:
        print(f"Erreur : {e}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python script.py <chemin_du_fichier_config> <log_dir>")
        sys.exit(1)

    config_path = sys.argv[1]
    log_dir = sys.argv[2]

    # Vérification si le fichier existe avant de l'utiliser
    if not os.path.isfile(config_path):
        print(f"[ERREUR] Le fichier {config_path} est introuvable.")
        sys.exit(1)

    try:
        config = load_config(config_path)
        print(f"Configuration chargée depuis {config_path}.")  # DEBUG
    except Exception as e:
        print(f"[ERREUR] Impossible de charger la configuration : {e}")
        sys.exit(1)

    main(config, log_dir)