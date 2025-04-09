# Pour lister les périphériques vidéo disponibles:
```
v4l2-ctl --list-devices
```

# Pour tester la capture vidéo avec FFmpeg et tester les périphériques vidéo:
```
ffmpeg -f v4l2 -video_size 1920x1080 -i /dev/video0 -t 10 output.mp4
```

# Pour voir en live la box
```
ffplay /dev/video0
```