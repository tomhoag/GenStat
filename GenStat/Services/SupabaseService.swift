import Foundation

/// Provides static methods for fetching generator data from the Supabase REST API.
///
/// All requests use the publishable API key for anonymous read access.
/// JSON responses are decoded with `snake_case` key conversion and
/// ISO 8601 date parsing (with and without fractional seconds).
///
/// Credentials are loaded from Info.plist, which expands build settings
/// defined in `Secrets.xcconfig`. See `Secrets.xcconfig.template` for the
/// required format.
struct SupabaseService {
    /// The Supabase project URL, populated from `Secrets.xcconfig` via Info.plist.
    private static let supabaseURL: String = {
        guard let url = Bundle.main.object(forInfoDictionaryKey: "SUPABASE_URL") as? String,
              !url.isEmpty else {
            fatalError(
                "SUPABASE_URL not configured. "
                + "Copy Secrets.xcconfig.template to Secrets.xcconfig and add your credentials."
            )
        }
        return url
    }()

    /// The Supabase publishable API key, populated from `Secrets.xcconfig` via Info.plist.
    private static let supabaseKey: String = {
        guard let key = Bundle.main.object(forInfoDictionaryKey: "SUPABASE_KEY") as? String,
              !key.isEmpty else {
            fatalError(
                "SUPABASE_KEY not configured. "
                + "Copy Secrets.xcconfig.template to Secrets.xcconfig and add your credentials."
            )
        }
        return key
    }()

    /// A shared JSON decoder configured for Supabase response format.
    ///
    /// Uses `snake_case` key conversion and a custom date strategy that
    /// accepts ISO 8601 timestamps with or without fractional seconds.
    static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let fractionalStrategy = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
        let standardStrategy = Date.ISO8601FormatStyle()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = try? Date(string, strategy: fractionalStrategy) {
                return date
            }
            if let date = try? Date(string, strategy: standardStrategy) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(string)"
            )
        }
        return decoder
    }()

    /// Performs an authenticated GET request against the Supabase REST API.
    /// - Parameters:
    ///   - path: The API endpoint path (e.g. `/rest/v1/generator_status`).
    ///   - query: The URL query string for filtering and ordering.
    /// - Returns: The raw response data.
    /// - Throws: `URLError` if the URL is invalid or the server returns a non-2xx status.
    private static func request(path: String, query: String) async throws -> Data {
        guard let url = URL(string: "\(supabaseURL)\(path)?\(query)") else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.setValue(supabaseKey, forHTTPHeaderField: "apikey")
        request.setValue("Bearer \(supabaseKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw URLError(.badServerResponse, userInfo: [
                NSLocalizedDescriptionKey: "Server returned status \(statusCode)"
            ])
        }
        return data
    }

    /// Performs an authenticated POST request against the Supabase REST API.
    /// - Parameters:
    ///   - path: The API endpoint path (e.g. `/rest/v1/device_tokens`).
    ///   - body: The JSON body data to send.
    /// - Returns: The raw response data.
    /// - Throws: `URLError` if the URL is invalid or the server returns a non-2xx status.
    @discardableResult
    private static func post(path: String, body: Data) async throws -> Data {
        guard let url = URL(string: "\(supabaseURL)\(path)") else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(supabaseKey, forHTTPHeaderField: "apikey")
        request.setValue("Bearer \(supabaseKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("resolution=merge-duplicates", forHTTPHeaderField: "Prefer")
        request.httpBody = body
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw URLError(.badServerResponse, userInfo: [
                NSLocalizedDescriptionKey: "Server returned status \(statusCode)"
            ])
        }
        return data
    }

    /// Registers or updates the APNs device token in the `device_tokens` table.
    /// - Parameter token: The hex-encoded device token string.
    /// - Throws: `URLError` on network or server failure.
    static func registerDeviceToken(_ token: String) async throws {
        let payload: [String: Any] = [
            "token": token,
            "platform": "ios"
        ]
        let body = try JSONSerialization.data(withJSONObject: payload)
        try await post(path: "/rest/v1/device_tokens?on_conflict=token", body: body)
    }

    /// Fetches the current generator status from the `generator_status` table.
    /// - Returns: The single ``GeneratorStatus`` row.
    /// - Throws: `URLError` on network failure or if no status row exists.
    static func fetchStatus() async throws -> GeneratorStatus {
        let data = try await request(
            path: "/rest/v1/generator_status",
            query: "id=eq.1&limit=1"
        )
        let statuses = try decoder.decode([GeneratorStatus].self, from: data)
        guard let status = statuses.first else {
            throw URLError(.cannotParseResponse, userInfo: [
                NSLocalizedDescriptionKey: "No status record found"
            ])
        }
        return status
    }

    /// Fetches a page of generator events from the `generator_events` table.
    /// - Parameters:
    ///   - offset: The number of rows to skip (for pagination).
    ///   - limit: The maximum number of rows to return.
    /// - Returns: An array of ``GeneratorEvent`` ordered by newest first.
    /// - Throws: `URLError` on network or decoding failure.
    static func fetchEvents(offset: Int = 0, limit: Int = 50) async throws -> [GeneratorEvent] {
        let data = try await request(
            path: "/rest/v1/generator_events",
            query: "order=created_at.desc&offset=\(offset)&limit=\(limit)"
        )
        return try decoder.decode([GeneratorEvent].self, from: data)
    }
}

/// Abstracts generator data fetching for dependency injection in tests.
protocol GeneratorDataFetching {
    func fetchStatus() async throws -> GeneratorStatus
    func fetchEvents(offset: Int, limit: Int) async throws -> [GeneratorEvent]
}

extension SupabaseService: GeneratorDataFetching {
    func fetchStatus() async throws -> GeneratorStatus {
        try await Self.fetchStatus()
    }

    func fetchEvents(offset: Int, limit: Int) async throws -> [GeneratorEvent] {
        try await Self.fetchEvents(offset: offset, limit: limit)
    }
}
