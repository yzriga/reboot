import subprocess
import time
import threading
from datetime import datetime
import importlib.util
import os
import sys
import re
import logging
from collections import Counter
import cv2
import numpy as np

stop_event = threading.Event()

def connect_adb(ip='192.168.1.122', port=5555):
    logging.info(f"tentative de connexion à {ip} ...")
    connection_status = subprocess.run(['adb', 'connect', f'{ip}:{port}'], capture_output=True)
    if "connected" not in str(connection_status.stdout):
        error_msg = str(connection_status.stdout)[2:-3]
        logging.error(f"connexion échouée, {error_msg}")
        sys.exit(1)

    logging.info("connexion réussie")


def get_pid(package_name, ip):
    result = subprocess.run(['adb', '-s', f'{ip}:5555', 'shell', 'pidof', package_name], capture_output=True, text=True)
    pid = result.stdout.strip()
    return int(pid) if pid else None


def is_app_in_foreground(package_name, ip):
    result = subprocess.run(
        ['adb', '-s', f'{ip}:5555', 'shell', 'dumpsys', 'window', '|', 'grep', 'mCurrentFocus'],
        capture_output=True, text=True)
    return package_name in result.stdout
    lines = output.splitlines()
    for line in lines:
        if "mResumedActivity" in line and package_name in line:
            return True

    return False


def initialize_logcat(log_file, ip):
    subprocess.run(['adb', '-s', f'{ip}:5555', 'logcat', '-c'])
    subprocess.run(['adb', '-s', f'{ip}:5555', 'logcat', '-G', '2M'])
    with open(log_file, 'w') as lf:
        subprocess.Popen(['adb', '-s', f'{ip}:5555', 'logcat'], stdout=lf)


import subprocess


def load_config(config_path):
    if not os.path.isfile(config_path):
        logging.error(f"le fichier de configuration {config_path} n'existe pas")
        sys.exit(1)
    
    spec = importlib.util.spec_from_file_location("config", config_path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def get_device_model(ip):
    result = subprocess.run(["adb", "-s", ip, "shell", "getprop", "ro.product.device"], capture_output=True, text=True, check=True)
    if result.returncode == 0:
        return result.stdout[:-1]
    else:
        logging.error("Erreur lors de la récupération du device model")
        return None

def get_os_version(ip, timeout=30):
    result = subprocess.run(["adb", "-s", ip, "shell", "getprop", "ro.build.version.incremental"], capture_output=True, text=True, check=True)
    if result.returncode == 0:
        return result.stdout[:-1]
    else:
        logging.error("Erreur lors de la récupération de la version")
        return None


def get_os_version_and_imei(ip, timeout=30):
    try:
        # Exécution de la commande pour obtenir la version de l'OS avec un timeout
        os_version_result = subprocess.run(
            ['adb', '-s', f'{ip}:5555', 'shell', 'getprop', 'ro.build.version.incremental'],
            capture_output=True, text=True, timeout=timeout
        )
        os_version = os_version_result.stdout.strip()

        # Exécution de la commande pour obtenir le numéro de série avec un timeout
        serial_number_result = subprocess.run(
            ['adb', '-s', f'{ip}:5555', 'shell', 'getprop'],
            capture_output=True, text=True, timeout=timeout
        )

        serial_number = ''
        for line in serial_number_result.stdout.splitlines():
            if 'serial' in line.lower():
                serial_number = line.split(': ')[1].strip().strip('[]')
                break

        os_version_serialnumber = f"{os_version}_{serial_number}"
        return os_version_serialnumber

    except subprocess.TimeoutExpired:
        # En cas de dépassement du délai
        print(f"La commande adb a dépassé le délai d'attente pour {ip}")
        return None


def monitor_processes(ip):
    packages = {
        'bbui': 'fr.bouyguestelecom.tv.bbui',
        'middleware': 'fr.bouyguestelecom.tv.middleware',
        'comedia': 'com.rtrk.comedia.service',
        'tr069': 'insight.tr069.client',
        'custo': 'fr.bouyguestelecom.agent.custo',
        'power': 'fr.bouyguestelecom.tv.power',
        'system_server': 'system_server'
    }

    critical_processes = ['middleware', 'comedia', 'system_server']

    current_pids = {name: get_pid(pkg, ip) for name, pkg in packages.items()}
    bbui_in_foreground = is_app_in_foreground(packages['bbui'], ip)
    pid_changes = []
    persistent_pid_changes = {name: 0 for name in ['tr069', 'custo', 'power']}

    print(f"[DEBUG] Initial PIDs: {current_pids}, bbui in foreground: {bbui_in_foreground}")

    while not stop_event.is_set():
        new_pids = {name: get_pid(pkg, ip) for name, pkg in packages.items()}
        new_bbui_in_foreground = is_app_in_foreground(packages['bbui'], ip)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[DEBUG] {current_time} - Current PIDs: {new_pids}, bbui in foreground: {new_bbui_in_foreground}")
        if current_pids['bbui'] != new_pids['bbui']:
            change_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pid_changes.append(f"bbui PID changed from {current_pids['bbui']} to {new_pids['bbui']} at {change_time}")

            if bbui_in_foreground:
                print("[ERROR] bbui PID a changé alors qu'il était au premier plan.")
                print("[ERROR] attente de 60secondes .")

                time.sleep(60)
                subprocess.run(['adb', 'disconnect', f'{ip}:5555'])
                stop_event.set()
                break
            else:
                current_pids['bbui'] = new_pids['bbui']
        bbui_in_foreground = new_bbui_in_foreground
        for name, new_pid in new_pids.items():
            if name == 'bbui':
                print("[ERROR] bbui PID a changé .")
                continue
            if new_pid != current_pids[name] and name in critical_processes:
                change_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                pid_changes.append(f"{name} PID changed from {current_pids[name]} to {new_pid} at {change_time}")
                current_pids[name] = new_pid

                if name in critical_processes:
                    print(f"[ERROR] {name} was killed.")
                    print("[ERROR] attente de 40secondes .")
                    time.sleep(40)
                    subprocess.run(['adb', 'disconnect', f'{ip}:5555'])
                    stop_event.set()
                    break

                if name in persistent_pid_changes:
                    persistent_pid_changes[name] += 1

        if current_pids['bbui']:
            bbui_in_foreground = new_bbui_in_foreground

        time.sleep(10)

    return pid_changes, persistent_pid_changes


def record_logs(log_file, error_log_file, ip):
    f3411_count = 0
    f3413_count = 0

    logging.debug(f"Lecture du fichier de logs: {log_file}")
    with open(log_file, 'r') as lf:
        log_content = lf.read()
    logging.debug(f"Contenu du fichier lu avec succès")

    logging.debug("Recherche des occurrences de LOG_ERROR dans le contenu des logs")
    log_error_entries = re.findall(r'.*LOG_ERROR.*', log_content)
    logging.debug(f"Nombre d'entrées trouvées contenant LOG_ERROR: {len(log_error_entries)}")

    formatted_errors = []
    for entry in log_error_entries:
        match = re.search(r'LOG_ERROR: (.*)', entry)
        if match:
            log_error_content = match.group(1).strip()
            if 'LIVE;F3411' in log_error_content:
                f3411_count += 1
            if 'LIVE;F3413' in log_error_content:
                f3413_count += 1

            elements = log_error_content.split(';')
            if len(elements) >= 4:
                formatted_error = ';'.join(elements[-4:])
                formatted_errors.append(formatted_error)

    error_counts = Counter(formatted_errors)
    grep_output = '|'.join([f"{error}={count}" if count > 1 else error for error, count in error_counts.items()])

    return f3411_count, f3413_count, grep_output



def setup_capture(hdmi, nouveau_fps=None):
    # Initialiser l'objet de capture vidéo
    cap = cv2.VideoCapture(hdmi)
    if not cap.isOpened():
        print("[ERREUR] Impossible d'ouvrir la source vidéo")
        return
    
    # ?Pourquoi définir une valeur de FPS inférieure, par exemple, 15
    if nouveau_fps != None:
        cap.set(cv2.CAP_PROP_FPS, nouveau_fps)

    # Vérifier que la modification a bien été appliquée
    frame_rate = cap.get(cv2.CAP_PROP_FPS)
    print(f"Le nouveau FPS est : {frame_rate}")

    return (cap, frame_rate)


def setup_ffmpeg(frame_height, frame_width, frame_rate, video_name):
    # Commande ffmpeg pour enregistrer la vidéo directement en MP4 avec codec H.264
    ffmpeg_cmd = [
        'ffmpeg',
        '-y',  # overwrite output file if it exists
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',
        '-s', f"{frame_height}x{frame_width}",  # taille de l'image
        '-r', f"{frame_rate}",  # taux de capture (FPS)
        '-i', '-',  # lire les données de stdin
        '-an',  # pas de capture audio
        '-vcodec', 'libx264',
        '-pix_fmt', 'yuv420p',
        video_name
    ]

    ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return ffmpeg_process


def save_frame(frame, ffmpeg_process, log_f, blackscreen_events, compteur_frames_noires, est_noir):
    frame_rate = 30
    seuil_frames_noires = frame_rate * 5  # Seuil pour 5 secondes de frames noires
    # Ajouter l'heure actuelle à la frame
    heure_actuelle = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cv2.putText(frame, heure_actuelle, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)

    # Envoyer la frame à ffmpeg pour l'enregistrement
    ffmpeg_process.stdin.write(frame.tobytes())

    # Convertir la frame en niveaux de gris
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Vérifier si la frame est noire
    if np.mean(gris) < 10:  # Ce seuil peut nécessiter un ajustement
        compteur_frames_noires += 1
        if compteur_frames_noires >= seuil_frames_noires and not est_noir:
            est_noir = True
            temps_event = datetime.now()
            blackscreen_events.append((temps_event, 'début'))
            log_f.write(f"{temps_event} - Écran noir détecté pendant plus de 5 secondes\n")
            print("[DEBUG] Écran noir détecté pendant plus de 5 secondes")
    else:
        if est_noir:
            temps_event = datetime.now()
            blackscreen_events.append((temps_event, 'fin'))
            log_f.write(f"{temps_event} - Fin de l'écran noir\n")
        compteur_frames_noires = 0
        est_noir = False

    return (compteur_frames_noires, est_noir)

def record_video(video_file, hdmi, log_file, blackscreen_events):
    cap, frame_rate = setup_capture(hdmi, 10)
    ffmpeg_process = setup_ffmpeg(int(cap.get(3)), int(cap.get(4)), frame_rate, video_file)
    # Ouvrir le fichier de log
    log_f = open(log_file, 'a')
    compteur_frames_noires = 0
    est_noir = False

    while cap.isOpened() and not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            break

        compteur_frames_noires, est_noir = save_frame(frame, ffmpeg_process, log_f, blackscreen_events, compteur_frames_noires, est_noir)

    log_f.close()

    # Attendre 20 secondes supplémentaires après l'arrêt du test
    if stop_event.is_set():
        logging.info("Test terminé, attente de 20 secondes supplémentaires avant l'arrêt de la vidéo.")
        time.sleep(40)

    # Relâcher toutes les ressources une fois le travail terminé
    cap.release()
    ffmpeg_process.stdin.close()
    ffmpeg_process.wait()


# Configurer le module logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


def generate_results_file(os_version_serialnumber, test_name, start_time, duration, f3411_count, f3413_count,
                          pid_changes, grep_output, persistent_pid_changes, result_file, test_duration,
                          blackscreen_events, initialize=False):
    mode = 'w' if initialize else 'a'
    with open(result_file, mode) as f:
        if initialize:
            f.write(f"Version: {os_version_serialnumber}\n")
            f.write(f"Test Name: {test_name}\n")
            f.write(f"Start Time: {start_time}\n")
            f.write(f"Heure prévue: {test_duration} \n")

        f.write(f"\nDuration (hours): {duration}\n")
        f.write(f"F3411 Count: {f3411_count}\n")
        f.write(f"F3413 Count: {f3413_count}\n")
        f.write(f"PID Changes: {pid_changes}\n")
        persistent_changes_str = ', '.join(
            [f"{key}: {value} changements" for key, value in persistent_pid_changes.items()])
        f.write(f"Persistent PID Changes: {persistent_changes_str}\n")
        f.write(f"Comments: {'|'.join(grep_output.splitlines())}\n")

        # Ajouter les événements d'écran noir
        total_black_screens = (len(blackscreen_events) + 1) // 2
        f.write(f"Blackscreen Events: {total_black_screens}:\n")
        for i in range(0, len(blackscreen_events), 2):
            debut = blackscreen_events[i][0]
            fin = blackscreen_events[i + 1][0] if i + 1 < len(blackscreen_events) else "N/A"
            f.write(f"Début: {debut}, Fin: {fin}\n")

