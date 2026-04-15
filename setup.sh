#!/bin/bash

# ==============================================================================
# RADIO MASTER INSTALLER (Monolith v1.3 + 57min Rubrics)
# Python 3.10.12 | Ryzen 9 VPS
# ==============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Списки директорий
DIRS=(
    "ad" "timesignals" "day_jingles" "night_jingles" "jingles" "news" "pip"
    "phonk" "raggatek" "dnb" "hardbass" "nudisco" "techno" "dubtech" "hiphop"
    "randomshit" "diy" "reggae" "jazz" "reading" "stellardrone" "downtempo"
    "trance" "pop"
)

FILES=(
    "config.ini" "hour.txt" "program.txt" "nouns_small.txt"
    "blacklistedwords.txt" "Flexi_IBM_VGA_False_437.ttf" "cover.png"
    "translate_prompt.txt" "prompt.txt"
)

APPS=("python3" "ffmpeg" "ffprobe" "screen" "mtr")

# --- Вспомогательные функции ---

confirm() {
    echo -e -n "${BLUE}>> $1 (y/n)? ${NC}"
    read -r answer
    if [[ "$answer" != [Yy]* ]]; then
        echo -e "${RED}Пропущено.${NC}"
        return 1
    fi
    return 0
}

check_status() {
    local missing_dirs=()
    local missing_files=()
    local missing_apps=()
    local missing_media=0

    echo -e "\n${YELLOW}--- ВЕРИФИКАЦИЯ ОКРУЖЕНИЯ ---${NC}"

    for app in "${APPS[@]}"; do
        if ! command -v "$app" &>/dev/null; then missing_apps+=("$app"); fi
    done
    for dir in "${DIRS[@]}"; do
        if [ ! -d "$dir" ]; then missing_dirs+=("$dir"); fi
    done
    for file in "${FILES[@]}"; do
        if [ ! -f "$file" ]; then missing_files+=("$file"); fi
    done
    if ! ls pip/*.mp4 &>/dev/null; then missing_media=1; fi

    [[ ${#missing_apps[@]} -eq 0 ]] && echo -e "[${GREEN}OK${NC}] Системное ПО" || echo -e "[${RED}FAIL${NC}] Отсутствует ПО: ${RED}${missing_apps[*]}${NC}"
    [[ ${#missing_dirs[@]} -eq 0 ]] && echo -e "[${GREEN}OK${NC}] Директории" || echo -e "[${RED}FAIL${NC}] Отсутствуют папки: ${RED}${missing_dirs[*]}${NC}"
    [[ ${#missing_files[@]} -eq 0 ]] && echo -e "[${GREEN}OK${NC}] Системные файлы" || echo -e "[${RED}FAIL${NC}] Отсутствуют файлы: ${RED}${missing_files[*]}${NC}"
    [[ $missing_media -eq 0 ]] && echo -e "[${GREEN}OK${NC}] Видео-оверлеи" || echo -e "[${RED}FAIL${NC}] В папке ${RED}pip/${NC} нет .mp4 файлов"

    return $(( ${#missing_dirs[@]} + ${#missing_files[@]} + ${#missing_apps[@]} + missing_media ))
}

# --- ГЕНЕРАЦИЯ МОКАПОВ ---

gen_cover_mock() {
    echo -e "${YELLOW}Генерация cover.png (1280x720)...${NC}"
    ffmpeg -y -f lavfi -i "color=c=0x1a1a2e:s=1280x720:d=1" \
           -vf "drawgrid=width=100:height=100:thickness=1:color=white@0.1" \
           -frames:v 1 "cover.png" -loglevel error
}

gen_movie_mock() {
    echo -e "${YELLOW}Генерация movie.mp4 (1280x720, 44100Hz)...${NC}"
    ffmpeg -y -f lavfi -i "smptebars=size=1280x720:duration=$2" \
           -f lavfi -i "sine=f=1000:d=$2:sample_rate=44100" \
           -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 44100 -b:a 128k \
           "$1" -loglevel error
}

gen_pip_mock() {
    echo -e "${YELLOW}Генерация оверлея $1 (640x360, No Audio)...${NC}"
    ffmpeg -y -f lavfi -i "testsrc=size=640x360:rate=25:duration=$2" \
           -c:v libx264 -pix_fmt yuv420p -an \
           "$1" -loglevel error
}

gen_audio_mock() {
    ffmpeg -y -f lavfi -i "sine=frequency=$3:duration=$2:sample_rate=44100" \
           -c:a aac -ar 44100 -b:a 128k "$1" -loglevel error
}

# Новая функция: Создает длинный трек путем зацикливания короткого семпла
gen_long_track_mock() {
    local TARGET_FILE=$1
    local FREQ=$2
    local TEMP_SEED="seed_temp.m4a"
    
    # 1. Создаем короткий "зерно" файл на 30 сек
    ffmpeg -y -f lavfi -i "sine=frequency=$FREQ:duration=30:sample_rate=44100" \
           -c:a aac -ar 44100 -b:a 128k "$TEMP_SEED" -loglevel error
           
    # 2. Растягиваем его до 57 минут (3420 сек) через stream_loop
    # Используем -c copy, так как параметры идентичны - это мгновенно.
    ffmpeg -y -stream_loop -1 -i "$TEMP_SEED" -t 3420 -c copy "$TARGET_FILE" -loglevel error
    
    rm "$TEMP_SEED"
}

# --- ОСНОВНАЯ ЛОГИКА ---

echo -e "${YELLOW}==============================================${NC}"
echo -e "${YELLOW}      RADIO MASTER SETUP: MONOLITH v1.3       ${NC}"
echo -e "${YELLOW}==============================================${NC}"

check_status
if [ $? -ne 0 ]; then
    if confirm "Попробовать создать недостающие папки"; then
        for dir in "${DIRS[@]}"; do mkdir -p "$dir"; done
        check_status
    fi
fi

if confirm "Сгенерировать контент (Кино, PIPx30, 57-мин Треки, Обложка)"; then
    
    [ ! -f "cover.png" ] && gen_cover_mock

    gen_movie_mock "movie.mp4" 120
    
    gen_pip_mock "pip/bg_overlay.mp4" 15
    echo -e "${YELLOW}Размножаю PIP-оверлеи (30 копий)...${NC}"
    for i in {01..30}; do cp "pip/bg_overlay.mp4" "pip/bg_$i.mp4"; done

    echo -e "${YELLOW}Создание аудио-заглушек (джинглы, реклама, время)...${NC}"
    gen_audio_mock "news/news.m4a" 30 900
    gen_audio_mock "jingles/jingle01.m4a" 30 1100
    gen_audio_mock "day_jingles/day_jingle01.m4a" 30 1150
    gen_audio_mock "night_jingles/night_jingle01.m4a" 30 1050
    gen_audio_mock "ad/ad01.m4a" 30 1200

    for h in {00..23}; do
        gen_audio_mock "timesignals/${h}oclock.m4a" 31 $((800 + 10#$h))
    done

    # Треки в жанры (теперь по 57 минут)
    for GENRE in "${DIRS[@]}"; do
        if [[ ! " ad timesignals day_jingles night_jingles jingles news pip " =~ " $GENRE " ]]; then
            echo -e "${YELLOW}Генерация 57-мин рубрики для $GENRE...${NC}"
            gen_long_track_mock "$GENRE/track1.m4a" $((900 + RANDOM % 100))
            gen_long_track_mock "$GENRE/track2.m4a" $((1000 + RANDOM % 100))
            gen_audio_mock "$GENRE/intro.m4a" 15 440
        fi
    done
fi

echo -e "\n${YELLOW}--- ИТОГОВАЯ ПРОВЕРКА ---${NC}"
check_status
final_code=$?

if [ $final_code -eq 0 ]; then
    echo -e "\n${GREEN}УСТАНОВКА ЗАВЕРШЕНА. Рубрики по 57 минут созданы.${NC}"
else
    echo -e "\n${RED}ВНИМАНИЕ: Не все проверки пройдены.${NC}"
fi

exit $final_code
