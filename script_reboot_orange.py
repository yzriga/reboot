import cv2
import time
import os
import subprocess
import sys
import logging
import numpy as np
from ..zap_ayanleh.zap_functions import load_config

# Paramètres
result_base_dir = "/home/benchmark/IVS/results/"
reference_image_path = "/home/benchmark/IVS/function/reboot/ref.png"
focus_region = (62, 50, 155, 147)
expected_kpi = 90.00

def reboot_via_pdu(pdu_config):
    ip, pdu = pdu_config.split()
    logging.info(f"Envoi commande OFF à la PDU {ip}...")
    subprocess.run(f"snmpset -v1 -c public {ip} {pdu} i 2", shell=True)  # Off
    time.sleep(1)
    logging.info("Commande ON envoyée à la PDU...")
    subprocess.run(f"snmpset -v1 -c public {ip} {pdu} i 1", shell=True)  # On

def compare_images(frame, template):
    threshold = 0.3
    try:
        ref_image = cv2.imread(template, cv2.IMREAD_GRAYSCALE)
        if ref_image is None:
            logging.error("Template image non trouvée !")
            return False

        grayscale_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        x1, y1, x2, y2 = focus_region
        cropped_frame = grayscale_frame[y1-10:y2+10, x1-10:x2+10]

        if cropped_frame.shape[0] < ref_image.shape[0] or cropped_frame.shape[1] < ref_image.shape[1]:
            logging.error("La ROI est plus petite que le template !")
            return False

        res = cv2.matchTemplate(cropped_frame, ref_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        logging.debug(f"Similarité détectée : {max_val:.2f}")
        return max_val >= threshold
    except Exception as e:
        logging.error(f"Erreur lors de la comparaison : {e}")
        return False

def detect_logo_in_video(video_path):
    if not os.path.exists(video_path):
        logging.error(f"Fichier vidéo introuvable : {video_path}")
        return None

    if reference_image_path is None:
        logging.error("Erreur : ref.png introuvable.")
        return False

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logging.error(f"Impossible d'ouvrir la vidéo {video_path}")
        return None

    frame_count = 0
    logo_time = None
    start_time = time.time()

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if frame_count % 10 == 0:
            if compare_images(frame, reference_image_path):
                logo_time = time.time() - start_time
                break
        frame_count += 1
    cap.release()
    return logo_time

def detect_stream_from_video(video_path, y1, y2, x1, x2, seuil_diff=5, frames_consecutives=20):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Erreur d'ouverture vidéo")
        return False, None

    ret, frame = cap.read()
    if not ret:
        print("Erreur lecture première frame")
        return False, None

    zone_precedente = frame[y1:y2, x1:x2]
    compteur = 0
    start_time = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        zone_courante = frame[y1:y2, x1:x2]

        if zone_courante.shape != zone_precedente.shape:
            zone_precedente = zone_courante
            continue

        difference = cv2.absdiff(zone_courante, zone_precedente)
        non_identiques = np.sum(difference > 10)
        total = difference.size
        pourcentage = (non_identiques / total) * 100

        if pourcentage > seuil_diff:
            compteur += 1
            if compteur >= frames_consecutives:
                temps_detection = time.time() - start_time
                return True, round(temps_detection, 2)
        else:
            compteur = 0

        zone_precedente = zone_courante

    return False, None
SAVE_PATH = os.path.join(os.path.expanduser("~"), "IVS/results/")

def measure_boot_time(config, log_dir):
    from ..vod import zap_functions

    path = os.path.join(SAVE_PATH, config.STB, "KPI", config.Version, "reboot")
    os.makedirs(path, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"reboot_{timestamp}.mp4"
    video_path = os.path.join(path, filename)

    results_file = os.path.join(path, "results.txt")
    file_exists = os.path.exists(results_file)
    file = open(results_file, "a")
    if not file_exists:
        file.write("Exemple, 90.0\n")

    log_file = os.path.join(log_dir, "log.txt")
    log_f = open(log_file, 'a')
    blackscreen_events = []

    cap, frame_rate = zap_functions.setup_capture(config.hdmi, 10)
    ffmpeg_process = zap_functions.setup_ffmpeg(int(cap.get(3)), int(cap.get(4)), frame_rate, video_path)

    # Capture initiale de 10 secondes avant le reboot
    initial_duration = 10  # secondes
    start_initial = time.time()
    compteur_frames_noires = 0
    est_noir = False
    while (time.time() - start_initial) < initial_duration:
        ret, frame = cap.read()
        if not ret:
            logging.error("Erreur de lecture pendant la capture initiale")
            break
        compteur_frames_noires, est_noir = zap_functions.save_frame(
            frame, ffmpeg_process, log_f, blackscreen_events, compteur_frames_noires, est_noir)

    # Reboot via PDU
    logging.info("Envoi reboot via PDU...")
    reboot_start = time.time()
    reboot_via_pdu(config.PDU)

    logo_detected = False
    flux_detected = False
    logo_time = 0
    stream_time = 0
    compteur_flux = 0
    compteur_frames = 0
    zone_precedente = None

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        compteur_frames_noires, est_noir = zap_functions.save_frame(
            frame, ffmpeg_process, log_f, blackscreen_events, compteur_frames_noires, est_noir)

        # Gestion du temps après détection
        if flux_detected:
            elapsed_post = time.time() - post_detect_start
            if elapsed_post >= 10:  # Arrêt après 10s supplémentaires
                break
            continue  # On continue d'enregistrer mais sans analyser

        compteur_frames += 1
        elapsed = time.time() - reboot_start

        # Détection logo
        if not logo_detected and compteur_frames % 10 == 0:
            similarity = compare_images(frame, reference_image_path)
            logging.debug(f"Similarité détectée : {similarity:.2f}")
            if similarity:
                logo_time = round(elapsed, 2)
                logo_detected = True
                logging.info(f"Logo détecté à {logo_time}s")

        # Détection flux
        if logo_detected and not flux_detected:
            y1, y2, x1, x2 = 146, 420, 92, 1094
            zone = frame[y1:y2, x1:x2]
            
            if zone_precedente is not None and zone.shape == zone_precedente.shape:
                diff = cv2.absdiff(zone, zone_precedente)
                pourcentage = (np.sum(diff > 10) / diff.size) * 100
                logging.debug(f"Différence mouvement : {pourcentage:.2f}%")

                if pourcentage > 5:
                    compteur_flux += 1
                    if compteur_flux >= 5:
                        stream_time = round(elapsed, 2)
                        flux_detected = True
                        post_detect_start = time.time()  # Démarre le timer post-détection
                        logging.info(f"Flux détecté à {stream_time}s")

                else:
                    compteur_flux = max(0, compteur_flux - 1)

            zone_precedente = zone

    cap.release()
    ffmpeg_process.stdin.close()
    ffmpeg_process.wait()
    log_f.close()

    final_time = logo_time if logo_detected else stream_time if flux_detected else 90.0
    file.write(f"{video_path}, {final_time}\n")
    file.close()
    logging.info(f"Mesure terminée : {final_time}s — Résultat enregistré dans {results_file}")

def main(config, log_dir):
    try:
        video_source = config.hdmi
        pdu_ip = config.PDU
        STB = config.STB

        if not video_source:
            logging.error("Aucune source vidéo définie dans la configuration.")
            sys.exit(1)

        os.makedirs(log_dir, exist_ok=True)
        measure_boot_time(config, log_dir)
    except Exception as e:
        logging.error(f"Erreur : {e}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        logging.debug("Usage : python script_reboot_orange.py <chemin_du_fichier_config> <log_dir>")
        sys.exit(1)

    config_path = sys.argv[1]
    log_dir = sys.argv[2]

    try:
        config = load_config(config_path)
    except Exception as e:
        logging.error(f"[ERREUR] Impossible de charger la configuration : {e}")
        sys.exit(1)

    main(config, log_dir)

