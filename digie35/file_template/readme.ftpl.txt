; Image filename template definition to allow set parameters related to particular image interactively.
; It is handy categorization by file name
; Pattern consists with series of parts which might be even conditional.
; Eg. IMG_BW_0001_AGFA_12
; Part value might effect another settings as LED or preset via actions

name: <human name as appears in GUI>
parts:
  <id>:                   ; unique identifier (letters, digits, underscore), referenced as variable from "if"
                          ; common options
    name: string          ; human friendly, appears in GUI
    used_in_pattern: boolean  ; to use a part just for an action, default: true
    prefix: string        ; prefix to be added if value is not empty
    suffix: string        ; suffix to be added if value is not empty
    enabled: boolean      ; disabled parts are skipped, default: true
    required: boolean     ; if a value must be entered to pass, default: true
    if: simple_eval       ; display/use conditionally, active when expression returns true, see https://pypi.org/project/simpleeval/
                          ; part values are passed as variables named by part id

                          ; type specific options
    type: "enum"
    values:
      - value: string     ; file part value
        name: string      ; human friendly as appears in GUI, default: <value>
        enabled: boolean  ; to show in GUI, default: true
      - value: ...

  <id2>:
    type: "datetime"      ; current system datetime
    format: fmtstr        ; Python's strftime() format, https://docs.python.org/3/library/datetime.html#format-codes, dafault: "%Y%m%d%H%M%S"

  <id3>:
    type: "counter"
    regex: regex          ; regular expression to get count from file name, e.g. "(\d+)$" for trailling counter IMG_04587.jpg
    digits: int           ; minimal number of digits, leading zeroes are prepended

  <id4>: 
    type: "static"        ; static expandable text, e.g. "{token}_text"
    value: string         ; supported tokens: {project_id}, {film_id}, {camera_filename}

  <id5>:
    type: "string"
    max_length: int       ; max length, default: unlimited
    regex: regex          ; validation Python's regular expression  

  <id6>:
    type: "number"
    min: int              ; minimal value, default: 1
    max: int              ; maximal value, default: 99999
    
effects:
  <id>:                   ; unique identifier
    if: simple_eval       ; see "if" above, does actions when expression returns true
    actions:
      - type: "set"       ; set value to an entity
        entity: string    ; entities: preset, led
        value: string     ; value to be assigned to entity