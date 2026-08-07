import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes with conditional logic (clsx + tailwind-merge). 复用 chatweb 同款。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
