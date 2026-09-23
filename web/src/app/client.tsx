import { createRoot } from "react-dom/client";

import "../styles/tokens.css";
import "../styles/yukina-shell.css";
import "../styles/yukina-upstream.css";
import StudioApp from "./StudioApp";

const mount = document.getElementById("studio-root");

if (!mount) {
  throw new Error("Studio mount element is missing");
}

createRoot(mount).render(<StudioApp />);
