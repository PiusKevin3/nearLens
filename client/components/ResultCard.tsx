export default function ResultCard({ result }: { result: any }) {
  return (
    <div className="w-full bg-gray-50 rounded-xl p-4 shadow-md mt-4">
      <h2 className="font-bold text-lg text-gray-800">Nearby Recommendations</h2>
      <ul className="mt-3 space-y-3">
        {result.places?.map((place: any, i: number) => (
          <li key={i} className="border-b pb-2">
            <strong>{place.name}</strong>
            <p className="text-sm text-gray-600">{place.address}</p>
            {place.rating && (
              <p className="text-yellow-600 text-sm">⭐ {place.rating}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
