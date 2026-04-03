import Testing
import Foundation
@testable import ShipyardBridgeLib

@Suite("FileInputStream")
struct FileInputStreamTests {

    private func makePipeStream() -> (stream: FileInputStream, writePipe: Pipe) {
        let pipe = Pipe()
        let stream = FileInputStream(handle: pipe.fileHandleForReading)
        return (stream, pipe)
    }

    private func write(_ text: String, to pipe: Pipe) {
        pipe.fileHandleForWriting.write(text.data(using: .utf8)!)
    }

    private func closeWrite(_ pipe: Pipe) {
        pipe.fileHandleForWriting.closeFile()
    }

    @Test("reads single line terminated by newline")
    func readsSingleLine() {
        let (stream, pipe) = makePipeStream()
        write("hello world\n", to: pipe)
        closeWrite(pipe)

        let line = stream.readLine()
        #expect(line == "hello world")
    }

    @Test("reads multiple lines sequentially")
    func readsMultipleLines() {
        let (stream, pipe) = makePipeStream()
        write("line1\nline2\nline3\n", to: pipe)
        closeWrite(pipe)

        #expect(stream.readLine() == "line1")
        #expect(stream.readLine() == "line2")
        #expect(stream.readLine() == "line3")
    }

    @Test("returns nil on EOF after all lines read")
    func returnsNilOnEOF() {
        let (stream, pipe) = makePipeStream()
        write("only\n", to: pipe)
        closeWrite(pipe)

        _ = stream.readLine()  // "only"
        let eof = stream.readLine()
        #expect(eof == nil)
    }

    @Test("returns nil immediately on empty closed pipe")
    func returnsNilOnEmptyInput() {
        let (stream, pipe) = makePipeStream()
        closeWrite(pipe)

        #expect(stream.readLine() == nil)
    }

    @Test("returns unterminated last line at EOF")
    func returnsUnterminatedLineAtEOF() {
        let (stream, pipe) = makePipeStream()
        write("no newline at end", to: pipe)
        closeWrite(pipe)

        let line = stream.readLine()
        #expect(line == "no newline at end")
    }

    @Test("handles empty lines between content")
    func handlesEmptyLines() {
        let (stream, pipe) = makePipeStream()
        write("first\n\nsecond\n", to: pipe)
        closeWrite(pipe)

        #expect(stream.readLine() == "first")
        #expect(stream.readLine() == "")
        #expect(stream.readLine() == "second")
    }

    @Test("handles long lines")
    func handlesLongLines() {
        let (stream, pipe) = makePipeStream()
        let longLine = String(repeating: "x", count: 10000)
        write(longLine + "\n", to: pipe)
        closeWrite(pipe)

        let line = stream.readLine()
        #expect(line == longLine)
    }

    @Test("handles Unicode content")
    func handlesUnicode() {
        let (stream, pipe) = makePipeStream()
        write("héllo wörld 🌍\n", to: pipe)
        closeWrite(pipe)

        #expect(stream.readLine() == "héllo wörld 🌍")
    }

    @Test("handles JSON line like MCP request")
    func handlesJSONLine() {
        let (stream, pipe) = makePipeStream()
        let json = "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\"}\n"
        write(json, to: pipe)
        closeWrite(pipe)

        let line = stream.readLine()
        #expect(line == "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\"}")
    }

    @Test("multiple reads after EOF all return nil")
    func multipleEOFReads() {
        let (stream, pipe) = makePipeStream()
        closeWrite(pipe)

        #expect(stream.readLine() == nil)
        #expect(stream.readLine() == nil)
        #expect(stream.readLine() == nil)
    }
}
