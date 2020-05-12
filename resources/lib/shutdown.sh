#! /bin/sh

echo 0 > /sys/class/rtc/rtc0/wakealarm
case "$2" in
    0)
        echo $1 > /sys/class/rtc/rtc0/wakealarm
    ;;
    1)
        echo $1 > /sys/class/rtc/rtc0/wakealarm
        case "$3" in
            0)
            shutdown -h now "PVR Manager shutdown the system"
            ;;
            1)
            systemctl suspend
            ;;
        esac
    ;;
    2)
        yard2wakeup -I $1
        case "$3" in
            0)
            shutdown -h now "PVR Manager shutdown the system"
            ;;
            1)
            systemctl suspend
            ;;
        esac
    ;;
esac
sleep 1
exit 0
