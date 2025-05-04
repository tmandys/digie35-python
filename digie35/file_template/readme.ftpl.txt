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
    editable: boolean     ; editable in GUI, default: true
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
    value: string         ; value of non-editable

  <id2>:
    type: "datetime"      ; current system datetime
    format: fmtstr        ; Python's strftime() format, https://docs.python.org/3/library/datetime.html#format-codes, dafault: "%Y%m%d%H%M%S"
                          ; if editable "NOW" will generate current datetime, otherwise entered string

  <id3>:
    type: "counter"
    regex: regex          ; regular expression to get count from file name, e.g. "(\d+)$" for trailling counter IMG_04587.jpg
    min: int              ; minimal value, default: 1
    digits: int           ; minimal number of digits, leading zeroes are prepended
    value: int            ; value of non-editable, will find unique number equal or greater

  <id4>:
    type: "string"        ; expandable text, e.g. "{token}_text"
    max_length: int       ; max length, default: unlimited
    regex: regex          ; validation Python's regular expression  
    value: string         ; supported tokens: {project_id}, {film_id}, {camera_filename} and partnames, e.g. {id2}

  <id5>:
    type: "number"
    min: int              ; minimal value, default: 1
    max: int              ; maximal value, default: 99999
    digits: int           ; minimal number of digits, leading zeroes are prepended
    value: int            ; value of non-editable

  <id6>:
    type: "bool"
    true_value: string    ; true value, default: "1"
    false_value: string   ; false value, default: "0"
    
effects:
  <id>:                   ; unique identifier
    if: simple_eval       ; see "if" above, does actions when expression returns true, default: True
    actions:
      - type: "set"       ; set value to an entity
        entity: string    ; entities: preset, led, autoinc
        value: simple_eval; value to be assigned to entity, fallback of expression is expression itself