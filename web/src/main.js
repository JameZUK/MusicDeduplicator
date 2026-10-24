import { mount } from 'svelte';
import '@fontsource-variable/fraunces';
import '@fontsource-variable/instrument-sans';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './app.css';
import App from './App.svelte';

mount(App, { target: document.getElementById('app') });
