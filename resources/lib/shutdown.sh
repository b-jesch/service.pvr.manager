#! /bin/sh

echo 0 > /sys/class/rtc/rtc0/wakealarm
case "$2" in
    1)
        echo $1 > /sys/class/rtc/rtc0/wakealarm
        shutdown -h now "PVR Manager shutdown the system"
    ;;
    2)
        yard2wakeup -l $1
        shutdown -h now "PVR Manager shutdown the system"
    ;;
esac
sleep 1
exit 0
