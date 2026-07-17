import { mount } from "svelte";
import Dictate from "./Dictate.svelte";

const dictate = mount(Dictate, { target: document.getElementById("dictate")! });

export default dictate;
