import "./App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import DubbingStudio from "./pages/DubbingStudio";

function App() {
  return (
    <div className="App grain min-h-screen">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<DubbingStudio />} />
        </Routes>
      </BrowserRouter>
      <Toaster
        position="top-right"
        theme="dark"
        toastOptions={{
          style: {
            background: "#121212",
            border: "1px solid #27272A",
            color: "#F8F9FA",
          },
        }}
      />
    </div>
  );
}

export default App;
