#!/bin/sh

#CMD=raspi-gpio
CMD=pinctrl

watch -d -n 0.1 "\
  echo -n 'Front:   '; $CMD get 5;\
  echo -n 'Rear:    '; $CMD get 6;\
  echo -n 'Middle:  '; $CMD get 7;\
  echo -n 'Adapter: '; $CMD get 8;\
  "
