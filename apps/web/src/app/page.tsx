import { redirect } from "next/navigation";
import { routes } from "@/lib/routes";

/**
 * There is no marketing page. The catalogue is the front door: a visitor lands
 * on the list of published subjects without signing in, because the contract
 * removes the signup wall.
 */
export default function HomePage() {
  redirect(routes.subjects);
}
