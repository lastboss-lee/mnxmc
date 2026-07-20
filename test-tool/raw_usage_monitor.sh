#!/bin/bash

BASE_DIR="/data/raw"
CACHE="/tmp/raw_usage_6h.cache"
INTERVAL=10

touch $CACHE

calculate_bucket() {

TMP="/tmp/raw_usage_scan.tmp"

find $BASE_DIR -type f -printf '%TY-%Tm-%Td %TH\n' > $TMP

awk '
{
    date=$1
    hour=$2

    if(hour<6) bucket="00-06"
    else if(hour<12) bucket="06-12"
    else if(hour<18) bucket="12-18"
    else bucket="18-24"

    print date" "bucket
}
' $TMP | sort -u > ${TMP}_bucket

while read DATE BUCKET
do

    KEY="${DATE}_${BUCKET}"

    if ! grep -q "^$KEY " $CACHE; then

        case $BUCKET in
            00-06) START="$DATE 00:00:00"; END="$DATE 06:00:00" ;;
            06-12) START="$DATE 06:00:00"; END="$DATE 12:00:00" ;;
            12-18) START="$DATE 12:00:00"; END="$DATE 18:00:00" ;;
            18-24) START="$DATE 18:00:00"; END="$DATE 23:59:59" ;;
        esac

        SIZE=$(find $BASE_DIR -type f -newermt "$START" ! -newermt "$END" -printf "%s\n" \
            | awk '{s+=$1} END {print s}')

        SIZE_GB=$(awk "BEGIN {printf \"%.2f\", $SIZE/1024/1024/1024}")

        echo "$KEY $SIZE_GB" >> $CACHE
    fi

done < ${TMP}_bucket

}

print_result() {

clear

echo "========== /data/raw 6H Usage =========="
echo "Update: $(date)"
echo

sort $CACHE | awk '
{
    split($1,a,"_")
    printf "%s %s   %10s GB\n",a[1],a[2],$2
}
'

echo
echo "TOTAL:"
awk '{s+=$2} END {printf "%.2f GB\n",s}' $CACHE

}

while true
do

    calculate_bucket
    print_result

    sleep $INTERVAL

done
