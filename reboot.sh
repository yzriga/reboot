#!/bin/bash
# Ajout du chemin au PYTHONPATH
export PYTHONPATH=~/IVS

# Fonction pour mettre à jour le STATUT dans le fichier de configuration
update_status() {
    config_file=$1
    new_status=$2
    sed -i "s/^STATUT *= *.*/STATUT = \"$new_status\"/" "$config_file"
    echo "$(date +'%Y-%m-%d %H:%M:%S') - Mise à jour du statut de $config_file à \"$new_status\""
}

# Fonction pour lancer un script avec redirection des logs
run_script() {
    config_file=$1
    log_dir=$2
    logfile=$(basename "$config_file").log

    # Mettre à jour le STATUT à "launch" avant de démarrer le test
    update_status "$config_file" "reboot"

    # Piège pour garantir la mise à jour du statut à "dispo" à la fin du script, même en cas d'erreur ou d'interruption
    trap "update_status '$config_file' 'dispo'; echo \"\$(date +'%Y-%m-%d %H:%M:%S') - Script $config_file terminé, statut mis à jour à 'dispo'\"" EXIT ERR SIGTERM

    echo "$(date +'%Y-%m-%d %H:%M:%S') - Lancement de script_reboot.py avec la configuration $config_file et redirection des logs vers $log_dir/$logfile"
    python3 -m function.reboot.script_reboot "$config_file" "$log_dir" > "$log_dir/$logfile" 2>&1 &
    pid=$!
    echo "$pid:$config_file" >> "$log_dir/pid_list.txt"
    echo "$(date +'%Y-%m-%d %H:%M:%S') - Enregistrement du PID $pid pour $config_file"

    # Attendre que le processus se termine
    wait $pid

    # Mettre à jour le STATUT à "dispo" après la fin du test (ceci est redondant avec le trap mais sert de sécurité supplémentaire)
    update_status "$config_file" "dispo"
    echo "$(date +'%Y-%m-%d %H:%M:%S') - Script $config_file terminé, statut mis à jour à \"dispo\""
}


# Fonction pour arrêter un script spécifique
stop_script() {
    config_file=$1
    echo "$(date +'%Y-%m-%d %H:%M:%S') - Tentative d'arrêt du script $config_file"
    # Lire le chemin du lien depuis le fichier de configuration
    log_dir=$(grep "^lien" "$config_file" | cut -d'=' -f2 | tr -d ' "')
    if [ -z "$log_dir" ]; then
        echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Aucun lien trouvé dans $config_file."
        exit 1
    fi

    echo "$(date +'%Y-%m-%d %H:%M:%S') - Lien récupéré : $log_dir"

    # Trouver le fichier *_results.txt dans log_dir
    results_file=$(find "$log_dir" -type f -name "*_results.txt" | head -n 1)
    if [ -z "$results_file" ]; then
        echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Aucun fichier *_results.txt trouvé dans $log_dir."
        exit 1
    fi

    echo "$(date +'%Y-%m-%d %H:%M:%S') - Fichier de résultats trouvé : $results_file"

    # Ajouter le message d'arrêt prématuré sur la même ligne que Comments:
    stop_message="Test arrêté prématurément par l'utilisateur via 'stop' ($(date +'%Y-%m-%d %H:%M:%S'))"
    sed -i "/^Comments:/ s/$/ $stop_message/" "$results_file"
    echo "$(date +'%Y-%m-%d %H:%M:%S') - Message ajouté à la ligne 'Comments:' dans le fichier de résultats."

    # Arrêter les processus associés
    if [ ! -f "$LOG_DIR/pid_list.txt" ]; then
        echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Aucun processus en cours trouvé."
        exit 1
    fi

    pids=$(grep -F "$config_file" "$LOG_DIR/pid_list.txt" | cut -d':' -f1)
    if [ -n "$pids" ]; then
        for pid in $pids; do
            echo "$(date +'%Y-%m-%d %H:%M:%S') - Arrêt du script $config_file avec PID $pid"
            kill "$pid"
            if [ $? -eq 0 ]; then
                echo "$(date +'%Y-%m-%d %H:%M:%S') - Script $config_file arrêté avec succès pour PID $pid."
                sed -i "/$pid:$config_file/d" "$LOG_DIR/pid_list.txt"
                update_status "$config_file" "dispo"  # Mettre à jour le statut après l'arrêt
            else
                echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Échec de l'arrêt du script $config_file pour PID $pid."
            fi
        done
    else
        echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Aucun processus trouvé pour $config_file"
    fi
}

# Fonction pour arrêter tous les processus
stop_all_scripts() {
    echo "$(date +'%Y-%m-%d %H:%M:%S') - Arrêt de tous les scripts en cours..."
    while IFS=: read -r pid file; do
        echo "$(date +'%Y-%m-%d %H:%M:%S') - Arrêt du processus avec PID $pid pour $file"
        kill "$pid"
        if [ $? -eq 0 ]; then
            echo "$(date +'%Y-%m-%d %H:%M:%S') - Processus $pid arrêté avec succès."
            update_status "$file" "dispo"  # Mettre à jour le statut après l'arrêt
        else
            echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Échec de l'arrêt du processus $pid."
        fi
    done < "$LOG_DIR/pid_list.txt"
    rm -f "$LOG_DIR/pid_list.txt"
    exit 1
}

# Capturer le signal SIGINT (généré par CTRL+C)
trap stop_all_scripts SIGINT

# Chemin vers le dossier de configurations
CONFIG_DIR=~/IVS/config

# Log de début de script
echo "$(date +'%Y-%m-%d %H:%M:%S') - Début de l'exécution de reboot.sh"
echo "$(date +'%Y-%m-%d %H:%M:%S') - Dossier de configurations : $CONFIG_DIR"

# Vérification du dossier de configurations
if [ ! -d "$CONFIG_DIR" ]; then
    echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Le dossier de configurations $CONFIG_DIR n'existe pas."
    exit 1
fi

# Définir le répertoire de log
LOG_DIR=~/IVS/logs

# Créer le répertoire de log s'il n'existe pas
mkdir -p "$LOG_DIR"

# Vérification si un argument est fourni
if [ $# -eq 1 ]; then
    config_file="$1"
    if [ "$config_file" == "stop_all" ]; then
        stop_all_scripts
    else
        # Vérifier si le chemin fourni est complet ou relatif
        if [[ "$config_file" != /* ]]; then
            config_file="$CONFIG_DIR/$config_file"
        fi

        if [ -f "$config_file" ]; then
            echo "$(date +'%Y-%m-%d %H:%M:%S') - Lancement de la configuration spécifique : $config_file"
            run_script "$config_file" "$LOG_DIR"
        else
            echo "$(date +'%Y-%m-%d %H:%M:%S') - [ERROR] Le fichier de configuration $config_file n'existe pas."
            exit 1
        fi
    fi
elif [ $# -eq 2 ] && [ "$1" == "stop" ]; then
    config_file="$2"
    # Vérifier si le chemin fourni est complet ou relatif
    if [[ "$config_file" != /* ]]; then
        config_file="$CONFIG_DIR/$config_file"
    fi
    stop_script "$config_file"
else
    # Parcourir tous les fichiers de configuration dans le dossier et les lancer
    for config_file in "$CONFIG_DIR"/*.py; do
        if [ -f "$config_file" ]; then
            echo "$(date +'%Y-%m-%d %H:%M:%S') - Trouvé le fichier de configuration : $config_file"
            run_script "$config_file" "$LOG_DIR" &
        else
            echo "$(date +'%Y-%m-%d %H:%M:%S') - Aucun fichier de configuration trouvé dans $CONFIG_DIR"
        fi
    done
fi

# Pas de `wait` ici, le script se termine immédiatement après avoir lancé tous les scripts en parallèle

# Log de fin de script
echo "$(date +'%Y-%m-%d %H:%M:%S') - Tous les scripts ont été lancés."
