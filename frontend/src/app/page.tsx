"use client";

import { usePageModel } from "./page.model";
import { LoginPage } from "./page.view";

export default function Home() {
  const methods = usePageModel();

  return <LoginPage {...methods} />;
}
