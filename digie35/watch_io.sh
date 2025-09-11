#!/bin/sh

#CMD=raspi-gpio
CMD=pinctrl

watch -d -n 0.1 "\
    echo -n 'LED: '; $CMD get 13;\
    echo -n 'PWM: '; $CMD get 12;\
    echo -n 'IO1: '; $CMD get 21;\
    echo -n 'IO2: '; $CMD get 20;\
    echo -n 'IO3: '; $CMD get 14;\
    echo -n 'IO4: '; $CMD get 19;\
    echo -n 'IO5: '; $CMD get 15;\
    #echo -n 'IO3-NIKI: '; $CMD get 26;\
    "
