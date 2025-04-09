import cv2

# === Chargement de la frame complète capturée (ex: menu TV) ===
frame_path = "toto.png"  # image complète
frame = cv2.imread(frame_path)

if frame is None:
    print("❌ Erreur : image 'toto.png' introuvable.")
    exit(1)

# === Coordonnées supposées du logo ===
# À ajuster si besoin — départ en (y1, y2) et (x1, x2)
y1, y2 = 150, 563  # hauteur (100px)
x1, x2 = 1025, 1868  # largeur (114px)

# === Extraction de la zone ===
logo_zone = frame[y1:y2, x1:x2]

# === Sauvegarde de la zone extraite pour inspection ===
cv2.imwrite("extrait_logo_zone.png", logo_zone)
print("✅ Zone extraite sauvegardée sous : extrait_logo_zone.png")

# === Affichage optionnel ===
cv2.imshow("Zone logo extraite", logo_zone)
cv2.waitKey(0)
cv2.destroyAllWindows()
