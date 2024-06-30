#!/bin/sh

watch -d -n 0.1 "\
    echo -n 'PWM: '; raspi-gpio get 12;\
    echo -n 'IO1: '; raspi-gpio get 21;\
    echo -n 'IO2: '; raspi-gpio get 20;\
    echo -n 'IO3: '; raspi-gpio get 14;\
    echo -n 'IO4: '; raspi-gpio get 19;\
    echo -n 'IO5: '; raspi-gpio get 15;\
    "
