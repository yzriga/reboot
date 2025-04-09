import subprocess
import pytesseract
import numpy as np
from multiprocessing import Process
from threading import Thread
import logging
import cv2 
import sys
import time
import os
import zap_functions

home_path = os.path.expanduser("~")
save_path = os.path.join(home_path, "IVS/results/")
expected_kpi = 3.50
number_of_zaps = 4


def stop_all(capture_hdmi, file, process_ffmpeg, log_f):
    # Close capture, output video, and opencv frame 
    file.close()
    process_ffmpeg.stdin.close()
    process_ffmpeg.wait()
    log_f.close()
    capture_hdmi.release()  
    logging.info("déconnexion réussie")

def create_repository(ip, save_path):
    path = save_path + zap_functions.get_device_model(ip) + "/KPI/" + zap_functions.get_os_version(ip) + "/zap/" 
    os.makedirs(path, exist_ok=True)

    return path


def setup_capture_hdmi(hdmi_path):
    # Create an object to read HDMI
    capture_hdmi = cv2.VideoCapture(hdmi_path) 
    if (capture_hdmi.isOpened() == False): 
        logging.error("erreur lors de la lecture du flux HDMI") 
        exit(1)

    return capture_hdmi

def write_zap_time(file, filepath, zap_time_taken):
    if zap_time_taken == 0:
        file.write(filepath + ", \n")
    else:
        file.write(filepath + ', ' + str(zap_time_taken) + "\n")

def zap_routine(ip, capture_hdmi, log_dir):
    # Create repository and file names
    path = create_repository(ip, save_path)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"zapping_{timestamp}0.mp4"

    # Gestion fichier résultat
    if os.path.exists(path+"results.txt"):
        file = open(f"{path}results.txt", "a")
    else:
        file = open(f"{path}results.txt", "a")
        file.write("Exemple, " + str(expected_kpi) + "\n")
        
    # Création de variables
    log_file = os.path.join(log_dir, "log.txt")
    blackscreen_events = []
    log_f = open(log_file, 'a')

    logging.info("placement sur la chaine 1...")
    # Going to the first channel
    subprocess.run(["adb", "-s", ip, "shell", "input", "keyevent", "KEYCODE_HOME"], check=True)
    time.sleep(2)
    logging.info("commande home entrée...")
    subprocess.run(["adb", "-s", ip, "shell", "input", "keyevent", "KEYCODE_1"], check=True)
    time.sleep(5)
    logging.info("commande chaine 1 entrée...")

    for channel_number in range(1, number_of_zaps+1):
        logging.info(f"enregistrement zap entre la chaine {channel_number} et {channel_number+1}...")
        # Changing file name of video
        filename = filename[0:-5] + str(channel_number) + filename[-4:]
        process_ffmpeg = zap_functions.setup_ffmpeg(int(capture_hdmi.get(3)), int(capture_hdmi.get(4)), 30, path+filename)
        zap_time_taken = manage_video(ip, capture_hdmi, process_ffmpeg, log_f, blackscreen_events)
        write_zap_time(file, path+filename, zap_time_taken)

    stop_all(capture_hdmi, file, process_ffmpeg, log_f)


def manage_video(ip, capture_hdmi, process_ffmpeg, log_f, blackscreen_events):
    status = "debut_video"
    timer = time.time()
    process = Process(target=press_key, args=(ip,))
    compteur_frames_noires = 0
    est_noir = False

    while True:
        ret, frame = capture_hdmi.read() 
        if not ret: 
            break 

        if time.time() - timer >= 5 and status != "zapping": # Check if timer has reached 5 seconds
            if status == "debut_video":
                # Pressing key in parallel while analysing frames
                if process.is_alive():  
                    process.join()
                process.start() 
                # Using timer to record zapping time
                timer = time.time() 
                logging.debug("bouton zap appuyé...")
                status = "zapping"

            if status == "fin_video":
                break
            
        if status == "zapping":
            if time.time() - timer >= 15 :
                logging.debug("délai d'attente dépassé...")
                zap_result = "erreur" 
                detect_stream.active = False
                detect_stream.frames_after_detection = 0
            else :
                zap_result = detect_zap(frame)

            if zap_result in ["flux", "erreur"]:
                logging.debug("fin temps de zap...")
                status = "fin_video"
                zap_time_taken = round(time.time() - timer, 2) if zap_result == "flux" else 0  
                timer = time.time() # Waiting 5 seconds before ending recording

        compteur_frames_noires, est_noir = zap_functions.save_frame(frame, process_ffmpeg, log_f, blackscreen_events, compteur_frames_noires, est_noir)
    return zap_time_taken

def press_key(ip):
    subprocess.run(["adb", "-s", ip, "shell", "input", "keyevent", "KEYCODE_CHANNEL_UP"], check=True)

def detect_zap(frame):
    if detect_logo(frame) and detect_stream.active == False:
        detect_stream(frame, first_use=True)

    msg = detect_error(frame)

    if detect_stream.active:
        logging.debug("recherche de flux...")
        if detect_error.on_screen:
            logging.info(msg)
            detect_stream.active = False
            detect_stream.frames_after_detection = 0
            return "erreur"

        if detect_stream(frame):
            detect_stream.frames_after_detection += 1

    # On analyse les 5 frames qui suivent la détection du flux
    if detect_stream.frames_after_detection != 0:
        if detect_stream.frames_after_detection >= 20:
            logging.info("flux détecté ...")
            detect_stream.frames_after_detection = 0
            detect_stream.active = False
            return "flux"
        else:
            detect_stream.frames_after_detection += 1

    return "rien"


def detect_stream(frame, first_use=False):
    cropped_frame = frame[6:285,150:568] 
    if first_use:
        detect_stream.active = True
        detect_stream.frames_after_detection = 0
        detect_stream.last_frame = cropped_frame
        return False

    # Calculate the difference between the two images
    difference = cv2.absdiff(cropped_frame, detect_stream.last_frame)
    non_identical_pixels = np.sum(difference > 10)
    total_pixels = difference.size
    percentage_difference = (non_identical_pixels / total_pixels) * 100
    logging.debug(f"Pourcentage de différence entre cette frame et la précédente : {round(percentage_difference,3)}")

    if percentage_difference > 5:
        return True

    detect_stream.last_frame = cropped_frame
    return False


def detect_logo(frame):
    # Checking presence of black areas
    black_area1 = 0 <= np.average(frame[361:426, 155:463]) < 7.653
    black_area2 = np.average(frame[79:229, 554:618]) <= 0.1
    channel_area = np.average(frame[4:475, 12:125]) > 20

    logo_visible = False
    logging.debug(f"pixels zone noire 1 (attendu ~7.65) : {round(np.average(frame[361:426, 155:463]),2)}")
    logging.debug(f"pixels zone noire 2 (attendu ~0.09) : {round(np.average(frame[79:229, 554:618]),2)}")
    logging.debug(f"pixels zone chaines (attendu > 20)  : {round(np.average(frame[4:475, 12:125]),2)}")

    if black_area1 and black_area2 and channel_area:
        # Check presence of channel logo
        gray = cv2.cvtColor(frame[6:283,141:568],cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)[1]

        contours = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        contours = contours[0] if len(contours) == 2 else contours[1]
        logo_visible = len(contours) > 0

        if logo_visible:
            return True

    return False


def detect_error(frame):
    detect_error.on_screen = False
    # Check if error screen is present
    blue_expected = np.array([103.5, 75.5, 29.7])
    red_expected = np.array([52, 50, 116])
    threshold = 20
    # Average pixel value on the blue and red area
    mean_color_blue = cv2.mean(frame[315:399, 374:411])
    logging.debug(f"rectangle bleu erreur : {mean_color_blue[:3]}")
    mean_color_red = cv2.mean(frame[411:473, 374:395])
    logging.debug(f"rectangle rouge erreur : {mean_color_red[:3]}")

    distance_blue = np.abs(blue_expected - mean_color_blue[:3])
    distance_red = np.abs(red_expected - mean_color_red[:3])

    blue_rectangle = np.all(distance_blue < threshold)
    red_rectangle =  np.all(distance_red < threshold)

    logging.debug(f"zone rouge -> {red_rectangle} / zone bleue -> {blue_rectangle}")

    if blue_rectangle and red_rectangle:
        # Retrieve error text
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resize_frame = cv2.resize(img_rgb[414:474, 382:632], None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
        top_text = pytesseract.image_to_string(img_rgb[14:96, 382:632])
        bottom_text = pytesseract.image_to_string(resize_frame)
        error_code = bottom_text[bottom_text.find(':') + 1:bottom_text.find('\n')].strip()
        top_text = top_text.replace("\n", " ").strip()
        
        if "erreur" in bottom_text:
            detect_error.on_screen = True
            return f"{top_text} (code erreur {error_code})"

    return None


    
def main(config, log_dir):
    # Checking the configuration file
    attributes = ["IP", "hdmi"]
    all_attributes_exist = all(hasattr(config, attr) for attr in attributes)
    
    if not all_attributes_exist:
        logging.error("attribut manquant dans le fichier de conf")
        sys.exit(1)

    zap_functions.connect_adb(config.IP)
    detect_stream.active = False
    detect_stream.frames_after_detection = 0
    capture_hdmi = setup_capture_hdmi(config.hdmi)

    zap_routine(config.IP, capture_hdmi, log_dir)

if __name__ == "__main__":
    # Checking CLI arguments 
    if len(sys.argv) != 3:
        print("Usage : python zap.py <chemin_du_fichier_config> <log_dir>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    log_dir = sys.argv[2]
    
    if not os.path.isfile(config_path):
        print(f"[ERREUR] Le fichier {config_path} est introuvable.")
        sys.exit(1)
    
    try:
        logging.debug(f"Fichier de configuration utilisé : {config_path}")
        logging.debug(f"Enregistrement des logs dans {log_dir}")
        config = zap_functions.load_config(config_path)
    except Exception as e:
        print(f"[ERREUR] Impossible de charger la configuration : {e}")
        sys.exit(1)
    
    main(config, log_dir)
