"use client";

import { useState } from "react";
import Image from "next/image";
import {API_BASE_URL} from "@/lib/api"

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null);
  const [response, setResponse] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    setFile(selectedFile);
    if (selectedFile) {
      setImagePreviewUrl(URL.createObjectURL(selectedFile));
    } else {
      setImagePreviewUrl(null);
    }
  };

  const getLocation = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setCoords({ lat: pos.coords.latitude, lon: pos.coords.longitude });
          alert("Location obtained!");
        },
        (err) => {
          console.error("Location error:", err);
          alert("Unable to access location. Please enable it in your browser.");
        }
      );
    } else {
      alert("Geolocation not supported in this browser.");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !coords) {
      alert("Please select an image and allow location access first!");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("latitude", coords.lat.toString());
    formData.append("longitude", coords.lon.toString());

    setLoading(true);
    setResponse(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      setResponse(data);
    } catch (error) {
      console.error("Upload error:", error);
      alert("Failed to upload image or get analysis.");
    } finally {
      setLoading(false);
      setFile(null);
      setImagePreviewUrl(null);
    }
  };

  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-6 bg-gradient-to-b from-red-50 to-white">
      {/* Header */}
      <h1 className="text-4xl font-extrabold text-red-600 mb-3 tracking-tight">📍 NearLens</h1>
      <p className="text-gray-700 text-center max-w-2xl mb-8 leading-relaxed">
        Discover nearby businesses, shops, and landmarks with just a photo and your location.
        Powered by image recognition and Google Places — NearLens helps you explore the world
        around you instantly.
      </p>

      {/* Form Card */}
      <form
        onSubmit={handleSubmit}
        className="bg-white p-6 rounded-2xl shadow-lg w-full max-w-md border border-red-100 space-y-4 mb-10"
      >
        {imagePreviewUrl && (
          <div className="flex justify-center mt-2">
            <Image
              src={imagePreviewUrl}
              alt="Image Preview"
              width={200}
              height={200}
              objectFit="contain"
              className="rounded-md border border-gray-300"
            />
          </div>
        )}

        <input
          type="file"
          accept="image/*"
          onChange={handleFileChange}
          className="border border-gray-300 text-gray-700 bg-gray-50 p-2 rounded-md w-full focus:ring-2 focus:ring-red-300 focus:outline-none"
        />

        {/* Black button for location */}
        <button
          type="button"
          onClick={getLocation}
          className="w-full py-2 rounded-lg bg-black text-white font-medium hover:bg-gray-800 transition"
          disabled={loading}
        >
          {coords
            ? `📍 Location: ${coords.lat.toFixed(4)}, ${coords.lon.toFixed(4)}`
            : "Get My Location"}
        </button>

        {/* Red button for upload */}
        <button
          type="submit"
          disabled={loading || !file || !coords}
          className="w-full py-2 rounded-lg bg-red-500 text-white font-medium hover:bg-red-600 transition"
        >
          {loading ? "Analyzing..." : "Upload & Analyze"}
        </button>
      </form>

      {/* Nearby Places */}
      {response && response.agent_response && (
        <div className="mt-6 bg-white p-6 rounded-xl shadow-md w-full max-w-5xl border border-red-100">
          <h2 className="text-xl font-semibold text-gray-800 mb-4">Nearby Places</h2>

          {response.agent_response.places && response.agent_response.places.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {response.agent_response.places.map((place: any, idx: number) => (
                <div
                  key={idx}
                  className="border border-gray-200 rounded-lg p-4 bg-red-50 hover:bg-red-100 transition"
                >
                  <p className="font-semibold text-gray-800">{place.name}</p>
                  <p className="text-sm text-gray-600">{place.address}</p>
                  <p className="text-sm text-gray-600">⭐ {place.rating || "N/A"}</p>
                  <p className="text-xs text-gray-500 mt-1">{place.types}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-700 mt-2">
              No specific textual response from the agent.
            </p>
          )}
        </div>
      )}

      {/* Error Section */}
      {response && response.status === "error" && (
        <div className="mt-6 bg-red-100 border border-red-400 text-red-700 p-4 rounded-lg shadow-md w-full max-w-md">
          <h2 className="text-lg font-semibold">Error</h2>
          <p className="mt-2">{response.error}</p>
        </div>
      )}
    </main>
  );
}
