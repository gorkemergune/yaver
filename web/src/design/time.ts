import { useEffect, useState } from "react";

/** Minutes since midnight, refreshed every 30 s: drives the "şu an" line. */
export function useNowMinutes(): number {
  const read = (): number => {
    const now = new Date();
    return now.getHours() * 60 + now.getMinutes();
  };
  const [minutes, setMinutes] = useState(read);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setMinutes(read());
    }, 30_000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  return minutes;
}

export function toMinutes(hhmm: string): number {
  const [h = "0", m = "0"] = hhmm.split(":");
  return Number(h) * 60 + Number(m);
}

export function greeting(minutes: number): string {
  const hour = Math.floor(minutes / 60);
  if (hour >= 5 && hour < 11) return "Günaydın";
  if (hour >= 11 && hour < 17) return "İyi günler";
  if (hour >= 17 && hour < 22) return "İyi akşamlar";
  return "İyi geceler";
}

const MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
const DAYS = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"];

export function todayLabel(date = new Date()): string {
  return `${String(date.getDate())} ${MONTHS[date.getMonth()] ?? ""} ${DAYS[date.getDay()] ?? ""}`;
}
