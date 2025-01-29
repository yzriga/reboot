import cv2
import time
import os
import numpy as np
import subprocess
import sys
import importlib.util

# Fonction pour vérifier si une frame est noire
def is_black_frame(frame, threshold=20):
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    avg_luminance = np.mean(gray_frame)
    return avg_luminance < threshold

# Fonction principale pour mesurer le temps de boot
def measure_boot_time(ip, video_source, result_dir, log_dir):
    # Vérifier et créer le répertoire de stockage des résultats
    if not os.path.exists(result_dir):
        os.makedirs(result_dir, exist_ok=True)

    result_file = os.path.join(result_dir, "results.txt")
    log_file = os.path.join(log_dir, "script_reboot.log")

    # Enregistrer les logs dans log_dir
    with open(log_file, "a") as log:
        log.write(f"Début du test avec IP: {ip}, Source vidéo: {video_source}\n")

    # Redémarrage de la box
    print("Redémarrage de la box...")
    subprocess.run(["adb", "-s", f"{ip}:5555", "reboot"])
    time.sleep(2)

    # Initialisation de la capture vidéo
    print(f"Utilisation de la source vidéo : {video_source}")  
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"Erreur : Impossible d'ouvrir la source vidéo {video_source}.")
        return

    frame_width = int(cap.get(3))
    frame_height = int(cap.get(4))
    frame_rate = cap.get(cv2.CAP_PROP_FPS)

    video_filename = os.path.join(result_dir, f"capture_{int(time.time())}.mp4")
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f"{frame_width}x{frame_height}", '-r', f"{frame_rate}", '-i', '-',
        '-an', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p', video_filename
    ]
    ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    boot_start_time = time.time()
    black_screen_start = None
    print("Attente de l'écran noir...")

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

                # Enregistrer les résultats
                with open(result_file, 'a') as f:
                    f.write(f"{video_filename},{boot_duration:.2f}\n")

                # Écrire dans les logs
                with open(log_file, "a") as log:
                    log.write(f"Temps de boot détecté : {boot_duration:.2f} secondes\n")

                break

        if ffmpeg_process:
            ffmpeg_process.stdin.write(frame.tobytes())

    cap.release()
    if ffmpeg_process:
        ffmpeg_process.stdin.close()
        ffmpeg_process.wait()

    print("Test terminé.")
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

        # Récupérer le dossier de stockage depuis le fichier de configuration
        if hasattr(config, 'lien'):
            result_dir = config.lien
        else:
            print("[ERREUR] Aucun chemin de stockage défini dans le fichier de configuration (manque 'lien').")
            sys.exit(1)

        # Vérifier et créer log_dir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        measure_boot_time(ip, video_source, result_dir, log_dir)

    except Exception as e:
        print(f"Erreur : {e}")

if __name__ == "__main__":
    print(f"Arguments reçus : {sys.argv}")  # DEBUG

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

