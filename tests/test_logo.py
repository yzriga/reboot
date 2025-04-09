import cv2
import time
import numpy as np
import logging

logging.basicConfig(level=logging.DEBUG)

def comparer_logos(zone, ref, seuil=0.5):
    if zone.shape != ref.shape:
        logging.warning("⚠️ Les tailles ne correspondent pas pour la comparaison.")
        return 0.0

    result = cv2.matchTemplate(zone, ref, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(result)
    return max_val

def attendre_logo_sans_capture(image_path, ref_path="ref.png", seuil=0.5):
    logging.info("📸 Chargement de l’image et extraction de la zone...")

    frame = cv2.imread(image_path)
    ref = cv2.imread(ref_path, cv2.IMREAD_GRAYSCALE)

    if frame is None or ref is None:
        logging.error("❌ Erreur de chargement des images.")
        return

    y1, y2 = 44, 158
    x1, x2 = 86, 186

    logo_zone = frame[y1:y2, x1:x2]
    if logo_zone.shape[0] == 0 or logo_zone.shape[1] == 0:
        logging.error("❌ Zone du logo vide.")
        return

    gray_zone = cv2.cvtColor(logo_zone, cv2.COLOR_BGR2GRAY)

    cv2.imwrite("zone_extraite_debug.png", gray_zone)
    cv2.imwrite("ref_debug.png", ref)

    score = comparer_logos(gray_zone, ref, seuil)
    logging.info(f"🎯 Similarité avec le logo : {score:.3f}")

    if score >= seuil:
        logging.info("✅ Logo détecté.")
    else:
        logging.info("❌ Logo non détecté.")

# Test avec une image locale
attendre_logo_sans_capture("toto.png", ref_path="ref.png", seuil=0.5)
