/** Only an explicitly launched local operator station uses the native print workspace. */
export function printEntry(stationMode = false): "/print" | "/get-a-quote" {
  return stationMode ? "/print" : "/get-a-quote";
}
