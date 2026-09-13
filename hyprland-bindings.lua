-- Place this snippet in ~/.config/hypr/bindings.lua

-- linux-voice / omarchy-dictate voice dictation
if o.cmd_present("linux-voice") or o.cmd_present("omarchy-dictate") then
  o.bind("SUPER + H", "Voice dictation", "linux-voice toggle")
  o.bind("SUPER + h", "Voice dictation", "linux-voice toggle")
end
