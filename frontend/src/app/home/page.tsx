"use client";

import { useHomeModel } from "./home.model";
import HomeView from "./home.view";

/* A rota só amarra ViewModel e View — é o formato MVVM dos demais projetos da
 * Level. O que ganha com isso: a View pode ser aberta num teste ou num Storybook
 * passando props na mão, sem subir os hooks que falam com a API. */
const Home = () => {
  const methods = useHomeModel();

  return <HomeView {...methods} />;
};

export default Home;
