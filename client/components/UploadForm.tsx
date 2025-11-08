"use client";
import { useState } from "react";
import { uploadImage } from "@/lib/api";
import ResultCard from "./ResultCard";
import Loader from "./Loader";

export default function UploadForm() {
    const [file, setFile] = useState<File | null>(null);
    const [result, setResult] = useState<any>(null);
    const [loading, setLoading] = useState(false);

    const handleUpload = async () => {
        if (!file) return;
        setLoading(true);
        try {
            const data = await uploadImage(file);
            setResult(data);
        } catch (err) {
            alert("Error uploading file");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex flex-col items-center gap-6 p-6 bg-white rounded-2xl shadow-lg w-full max-w-lg">
            <input
                type="file"
                accept="image/*"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="w-full px-3 py-2 rounded-md border border-gray-300 bg-gray-100 text-gray-700 cursor-pointer hover:bg-gray-200 transition"
            />

            <button
                onClick={handleUpload}
                className="bg-red-600 text-white px-6 py-2 rounded-md hover:bg-red-700"
            >
                Analyze & Find Nearby
            </button>

            {loading && <Loader />}
            {result && <ResultCard result={result} />}
        </div>
    );
}
