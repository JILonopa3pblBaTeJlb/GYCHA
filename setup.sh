#!/bin/bash

# ==============================================================================
# RADIO MASTER INSTALLER (Monolith + Cover Gen)
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

# Критические файлы
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

    if [ ${#missing_apps[@]} -eq 0 ]; then
        echo -e "[${GREEN}OK${NC}] Системное ПО"
    else
        echo -e "[${RED}FAIL${NC}] Отсутствует ПО: ${RED}${missing_apps[*]}${NC}"
    fi

    if [ ${#missing_dirs[@]} -eq 0 ]; then
        echo -e "[${GREEN}OK${NC}] Директории"
    else
        echo -e "[${RED}FAIL${NC}] Отсутствуют папки: ${RED}${missing_dirs[*]}${NC}"
    fi

    if [ ${#missing_files[@]} -eq 0 ]; then
        echo -e "[${GREEN}OK${NC}] Системные файлы"
    else
        echo -e "[${RED}FAIL${NC}] Отсутствуют файлы: ${RED}${missing_files[*]}${NC}"
    fi

    if [ $missing_media -eq 0 ]; then
        echo -e "[${GREEN}OK${NC}] Видео-оверлеи"
    else
        echo -e "[${RED}FAIL${NC}] В папке ${RED}pip/${NC} нет .mp4 файлов"
    fi

    return $(( ${#missing_dirs[@]} + ${#missing_files[@]} + ${#missing_apps[@]} + missing_media ))
}

# --- ГЕНЕРАЦИЯ МОКАПОВ ПО СПЕКАМ ---

# Создание cover.png (1280x720)
gen_cover_mock() {
    echo -e "${YELLOW}Генерация cover.png (1280x720)...${NC}"
    # Генерируем простое изображение: темно-синий фон с технической сеткой
    ffmpeg -y -f lavfi -i "color=c=0x1a1a2e:s=1280x720:d=1" \
           -vf "drawgrid=width=100:height=100:thickness=1:color=white@0.1" \
           -frames:v 1 "cover.png" -loglevel error
}

# 1280x720 | Audio: 44100Hz
gen_movie_mock() {
    echo -e "${YELLOW}Генерация movie.mp4 (1280x720, 44100Hz)...${NC}"
    ffmpeg -y -f lavfi -i "smptebars=size=1280x720:duration=$2" \
           -f lavfi -i "sine=f=1000:d=$2:sample_rate=44100" \
           -c:v libx264 -pix_fmt yuv420p -c:a aac -ar 44100 -b:a 128k \
           "$1" -loglevel error
}

# 640x360 | No Audio
gen_pip_mock() {
    echo -e "${YELLOW}Генерация оверлея $1 (640x360, No Audio)...${NC}"
    ffmpeg -y -f lavfi -i "testsrc=size=640x360:rate=25:duration=$2" \
           -c:v libx264 -pix_fmt yuv420p -an \
           "$1" -loglevel error
}

# Audio 44100Hz
gen_audio_mock() {
    ffmpeg -y -f lavfi -i "sine=frequency=$3:duration=$2:sample_rate=44100" \
           -c:a aac -ar 44100 -b:a 128k "$1" -loglevel error
}

# --- ОСНОВНАЯ ЛОГИКА ---

echo -e "${YELLOW}==============================================${NC}"
echo -e "${YELLOW}      RADIO MASTER SETUP: MONOLITH v1.1       ${NC}"
echo -e "${YELLOW}==============================================${NC}"

# Проверка 1
check_status
if [ $? -ne 0 ]; then
    if confirm "Попробовать создать недостающие папки"; then
        for dir in "${DIRS[@]}"; do mkdir -p "$dir"; done
        check_status
    fi
fi

# Генерация
if confirm "Сгенерировать тестовые мокапы (Кино, PIP, Аудио, Обложка)"; then
    
    # Генерация обложки, если её нет
    if [ ! -f "cover.png" ]; then
        gen_cover_mock
    fi

    # Фильм и фон
    gen_movie_mock "movie.mp4" 120
    gen_pip_mock "pip/bg_overlay.mp4" 15

    # Служебные файлы
    echo -e "${YELLOW}Создание аудио-заглушек...${NC}"
    gen_audio_mock "news/news.m4a" 30 900
    gen_audio_mock "jingles/jingle01.m4a" 30 1100
    gen_audio_mock "day_jingles/day_jingle01.m4a" 30 1150
    gen_audio_mock "night_jingles/night_jingle01.m4a" 30 1050
    gen_audio_mock "ad/ad01.m4a" 30 1200

    # Сигналы времени
    for h in {00..23}; do
        gen_audio_mock "timesignals/${h}oclock.m4a" 31 $((800 + 10#$h))
    done

    # Треки в жанры
    for GENRE in "${DIRS[@]}"; do
        if [[ ! " ad timesignals day_jingles night_jingles jingles news pip " =~ " $GENRE " ]]; then
            gen_audio_mock "$GENRE/track1.m4a" 35 $((900 + RANDOM % 200))
            gen_audio_mock "$GENRE/track2.m4a" 35 $((900 + RANDOM % 200))
            gen_audio_mock "$GENRE/intro.m4a" 31 440
        fi
    done
fi

# Финальный отчет
echo -e "\n${YELLOW}--- ИТОГОВАЯ ПРОВЕРКА ПЕРЕД ЗАПУСКОМ ---${NC}"
check_status
final_code=$?

if [ $final_code -eq 0 ]; then
    echo -e "\n${GREEN}УСТАНОВКА ЗАВЕРШЕНА. Все параметры и ресурсы на месте.${NC}"
else
    echo -e "\n${RED}ВНИМАНИЕ: Некоторые файлы (например, конфиги или шрифты) нужно добавить вручную.${NC}"
fi

exit $final_code
