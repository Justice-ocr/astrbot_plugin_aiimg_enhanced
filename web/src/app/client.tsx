import { createRoot } from "react-dom/client";

import StudioApp from "./StudioApp";

const mount = document.getElementById("studio-root");

if (!mount) {
  throw new Error("Studio mount element is missing");
}

createRoot(mount).render(<StudioApp />);
