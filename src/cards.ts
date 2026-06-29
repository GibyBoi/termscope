import { mount } from "svelte";
import Cards from "./Cards.svelte";
import "./cards.css";

const cards = mount(Cards, { target: document.getElementById("cards")! });

export default cards;
