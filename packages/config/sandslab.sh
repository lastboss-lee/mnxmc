# /etc/profile.d/sandslab.sh
# ===== SANDS LAB 전역 설정 =====
# 색상 설정
export LS_COLORS="\
rs=0:\
di=1;36:\
ln=1;35:\
so=1;35:\
pi=1;33:\
ex=1;31:\
bd=1;33:\
cd=1;33:\
*.tar=0;31:*.tgz=0;31:*.zip=0;31:*.gz=0;31:*.bz2=0;31:*.xz=0;31:\
*.jpg=0;35:*.jpeg=0;35:*.png=0;35:*.gif=0;35:*.mp4=0;35:*.mp3=0;35:*.aac=0;35:*.mkv=0;35:\
"
alias ls='ls --color=auto'
# 히스토리 시간 표시
export HISTTIMEFORMAT="%Y-%m-%d %H:%M:%S "
# mnxmon alias
alias mnxmon='watch -n 1 '\''curl -s http://localhost:9200/arkime_stats/_doc/$(hostname) | jq "._source | {totalPackets, packetQueue, closeQueue, totalDropped}"'\'''
# ===== 배너 출력 =====
if [ -z "$SANDSLAB_BANNER_SHOWN" ]; then
    export SANDSLAB_BANNER_SHOWN=1
    clear
    echo -e "\e[1;36m"
    cat <<'BANNER'
███╗   ███╗███╗   ██╗██╗  ██╗    ███╗   ██╗██████╗ ██████╗
████╗ ████║████╗  ██║╚██╗██╔╝    ████╗  ██║██╔══██╗██╔══██╗
██╔████╔██║██╔██╗ ██║ ╚███╔╝     ██╔██╗ ██║██║  ██║██████╔╝
██║╚██╔╝██║██║╚██╗██║ ██╔██╗     ██║╚██╗██║██║  ██║██╔══██╗
██║ ╚═╝ ██║██║ ╚████║██╔╝ ██╗    ██║ ╚████║██████╔╝██║  ██║
╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝    ╚═╝  ╚═══╝╚═════╝ ╚═╝  ╚═╝
BANNER
    echo -e "\e[1;33m                    SANDS LAB Inc. NDR SOLUTION SYSTEM \e[0m"
    echo

    echo -e "\e[1;36m╔══════════════════════════════════════════════════════════╗\e[0m"
    echo -e "\e[1;36m║\e[0m                                                          \e[1;36m║\e[0m"

    USER_TEXT="Logged in as: $USER"
    USER_PADDING=$(( (58 - ${#USER_TEXT}) / 2 ))
    printf "\e[1;36m║\e[0m%*s\e[1;32m%s\e[0m%*s\e[1;36m║\e[0m\n" $USER_PADDING "" "$USER_TEXT" $(( 58 - USER_PADDING - ${#USER_TEXT} )) ""

    if [ "$UID" -eq 0 ]; then
        ROLE_TEXT="Role: Administrator (root)"
    else
        ROLE_TEXT="Role: User"
    fi
    ROLE_PADDING=$(( (58 - ${#ROLE_TEXT}) / 2 ))
    printf "\e[1;36m║\e[0m%*s\e[1;33m%s\e[0m%*s\e[1;36m║\e[0m\n" $ROLE_PADDING "" "$ROLE_TEXT" $(( 58 - ROLE_PADDING - ${#ROLE_TEXT} )) ""

    echo -e "\e[1;36m║\e[0m                                                          \e[1;36m║\e[0m"

    TIME_TEXT="Session started: $(date '+%Y-%m-%d %H:%M:%S')"
    TIME_PADDING=$(( (58 - ${#TIME_TEXT}) / 2 ))
    printf "\e[1;36m║\e[0m%*s\e[1;37m%s\e[0m%*s\e[1;36m║\e[0m\n" $TIME_PADDING "" "$TIME_TEXT" $(( 58 - TIME_PADDING - ${#TIME_TEXT} )) ""

    echo -e "\e[1;36m║\e[0m                                                          \e[1;36m║\e[0m"
    echo -e "\e[1;36m╚══════════════════════════════════════════════════════════╝\e[0m"
    echo
fi
