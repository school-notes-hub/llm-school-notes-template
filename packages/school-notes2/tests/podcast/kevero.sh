#!/bin/sh
# Podcast mix (owner-approved 2026-10-08, „tökéletes”): only the owner's Suno track (paid plan) at both ends.
# Usage: kevero.sh <voice.mp3> <out.mp3> [music.mp3 = ~/jegyzet/podcast-zene/outro.mp3]
# Start: the track's first 20 s - full for 8 s, slow fade to 50 % by 11.5 s, quick drop to 5 % by 12 s (voice starts at 12 s),
# then out by 16 s. End: the track's last 20 s - starts 6 s before the voice ends at 10 -> 18 %, rises to full in 1.5 s after
# the last word, the track's own ending closes the episode. Voice loudness-normalised alone (no pumping), music at fixed gain.
set -eu
V=$1; OUT=$2; M=${3:-$HOME/jegyzet/podcast-zene/outro.mp3}
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$V")
OS=$(python3 -c "print(int((12+$D-6)*1000))")
ffmpeg -y -v error -i "$M" -i "$V" -sseof -20 -i "$M" -filter_complex "\
[0:a]aresample=48000,atrim=0:20,asetpts=PTS-STARTPTS,volume=0.7,volume='if(lt(t,8),1,if(lt(t,11.5),1-0.5*(t-8)/3.5,if(lt(t,12),0.5-0.45*(t-11.5)/0.5,if(lt(t,16),0.05*(1-(t-12)/4),0))))':eval=frame[i];\
[1:a]aresample=48000,loudnorm=I=-16:TP=-2:LRA=11,aresample=48000,aformat=channel_layouts=stereo,adelay=12000|12000[v];\
[2:a]aresample=48000,asetpts=PTS-STARTPTS,volume=0.7,volume='if(lt(t,6),0.10+0.08*t/6,if(lt(t,7.5),0.18+0.82*(t-6)/1.5,1))':eval=frame,adelay=$OS|$OS[o];\
[i][v][o]amix=inputs=3:normalize=0,alimiter=limit=0.89[a]" -map "[a]" -c:a libmp3lame -b:a 128k -ac 2 -bitexact "$OUT"
