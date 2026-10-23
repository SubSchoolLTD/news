import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({plugins:[vue()],server:{port:Number(process.env.VITE_PORT||5173),strictPort:true,proxy:{'/api':process.env.API_PROXY||'http://127.0.0.1:8010'}},build:{outDir:'dist',emptyOutDir:true}})
