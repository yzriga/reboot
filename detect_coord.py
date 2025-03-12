import cv2

# Charger une image (ex: une capture de ton flux HDMI)
image = cv2.imread("frame.png")

def get_mouse_coordinates(event, x, y, flags, param):
    """ Fonction appelée lorsqu'on clique sur l'image. """
    if event == cv2.EVENT_LBUTTONDOWN:  # Clic gauche
        print(f"Coordonnées : X={x}, Y={y}")

        # Afficher un cercle à l'endroit du clic
        cv2.circle(image, (x, y), 5, (0, 255, 0), -1)
        cv2.imshow("Image", image)

# Afficher l'image
cv2.imshow("Image", image)
cv2.setMouseCallback("Image", get_mouse_coordinates)
cv2.waitKey(0)  # Attendre une touche pour fermer la fenêtre
cv2.destroyAllWindows()
