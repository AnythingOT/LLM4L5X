// Pump with seal-in, stop and fault
Pump := (Start_PB OR Pump) AND NOT Stop_PB AND NOT Fault;

// High level alarm after 5 s. Name the timer so other rungs can use its .DN
IF DELAY(Level > 80.0, 5s, High_Tmr) THEN SET High_Alarm;
IF RISE(Ack_PB) AND NOT High_Tmr.DN THEN RESET High_Alarm;

// Count pump starts
IF RISE(Pump) THEN COUNT_UP(Pump_Starts, 1000), Run_Count := Run_Count + 1;
