import Foundation

// MARK: - FileInputStream Helper

public class FileInputStream {
    private let handle: FileHandle
    private var buffer = ""

    public init(handle: FileHandle) {
        self.handle = handle
    }

    public func readLine() -> String? {
        while !buffer.contains("\n") {
            let data = handle.availableData
            guard data.count > 0 else {
                // EOF
                if !buffer.isEmpty {
                    let line = buffer
                    buffer = ""
                    return line
                }
                return nil
            }

            guard let chunk = String(data: data, encoding: .utf8) else {
                continue
            }

            buffer.append(chunk)
        }

        guard let newlineIdx = buffer.firstIndex(of: "\n") else {
            return nil
        }

        let line = String(buffer[..<newlineIdx])
        buffer.removeFirst(buffer.distance(from: buffer.startIndex, to: buffer.index(after: newlineIdx)))

        return line
    }
}
