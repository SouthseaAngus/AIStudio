// Turns a folder of overlapping photos into a 3D model with Apple's Object Capture.
// Build with ./build.sh. Run ./photoscan --help for usage.

import Foundation
import RealityKit

let usage = """
Usage: photoscan <photos-folder> <output> [options]

  <output>            A path ending in .usdz writes one file.
                      Any other path is a folder that gets an OBJ, its material and textures.

Options:
  --detail <level>    preview, reduced, medium (default), full or raw
  --sequential        Photos are in the order they were taken, each overlapping the next
  --high-sensitivity  Find more matching points, for low-texture subjects (slower)
  --keep-background   Keep the surroundings instead of isolating the object
  --help              Show this message
"""

struct Arguments {
    var input: URL
    var output: URL
    var detail = PhotogrammetrySession.Request.Detail.medium
    var configuration = PhotogrammetrySession.Configuration()
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("Error: \(message)\n".utf8))
    exit(1)
}

func parseArguments() -> Arguments {
    var paths: [String] = []
    var detail = PhotogrammetrySession.Request.Detail.medium
    var configuration = PhotogrammetrySession.Configuration()

    var remaining = Array(CommandLine.arguments.dropFirst())[...]
    while let argument = remaining.popFirst() {
        switch argument {
        case "--help", "-h":
            print(usage)
            exit(0)
        case "--detail":
            switch remaining.popFirst() {
            case "preview": detail = .preview
            case "reduced": detail = .reduced
            case "medium": detail = .medium
            case "full": detail = .full
            case "raw": detail = .raw
            default: fail("--detail must be preview, reduced, medium, full or raw")
            }
        case "--sequential":
            configuration.sampleOrdering = .sequential
        case "--high-sensitivity":
            configuration.featureSensitivity = .high
        case "--keep-background":
            configuration.isObjectMaskingEnabled = false
        case _ where argument.hasPrefix("--"):
            fail("unknown option \(argument)\n\n\(usage)")
        default:
            paths.append(argument)
        }
    }

    guard paths.count == 2 else {
        print(usage)
        exit(1)
    }
    return Arguments(
        input: URL(fileURLWithPath: paths[0], isDirectory: true),
        output: URL(fileURLWithPath: paths[1], isDirectory: !paths[1].lowercased().hasSuffix(".usdz")),
        detail: detail,
        configuration: configuration
    )
}

@main
struct PhotoScan {
    static func main() async {
        setvbuf(stdout, nil, _IOLBF, 0)  // Show messages straight away, even when output goes to a log file.
        let arguments = parseArguments()

        guard PhotogrammetrySession.isSupported else {
            fail("Object Capture isn't supported on this Mac.")
        }

        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: arguments.input.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            fail("photos folder not found: \(arguments.input.path)")
        }

        // Object Capture writes an OBJ into a folder, which must already exist.
        // The .usdz file's parent folder has to exist too.
        let writesFile = arguments.output.pathExtension.lowercased() == "usdz"
        let folderToCreate = writesFile ? arguments.output.deletingLastPathComponent() : arguments.output
        do {
            try FileManager.default.createDirectory(at: folderToCreate, withIntermediateDirectories: true)
        } catch {
            fail("couldn't create \(folderToCreate.path): \(error.localizedDescription)")
        }

        let session: PhotogrammetrySession
        do {
            session = try PhotogrammetrySession(input: arguments.input, configuration: arguments.configuration)
            try session.process(requests: [.modelFile(url: arguments.output, detail: arguments.detail)])
        } catch {
            fail("couldn't start: \(error)")
        }

        var finishedOK = false
        var skipped = 0
        var lastPercent = -1

        do {
            // The stream stays open after the work ends, so stop at .processingComplete.
            outputs: for try await output in session.outputs {
                switch output {
                case .processingComplete:
                    break outputs
                case .requestProgress(_, let fraction):
                    let percent = Int(fraction * 100)
                    if percent != lastPercent {
                        lastPercent = percent
                        print("\rProcessing: \(percent)%", terminator: "")
                        fflush(stdout)
                    }
                case .invalidSample(let id, let reason):
                    print("\nPhoto \(id) rejected: \(reason)")
                case .skippedSample:
                    skipped += 1
                case .automaticDownsampling:
                    print("\nPhotos were downsampled to fit in memory.")
                case .requestComplete(_, .modelFile(let url)):
                    finishedOK = true
                    print("\nSaved: \(url.path)")
                case .requestError(_, let error):
                    print("\nFailed: \(error)")
                case .processingCancelled:
                    print("\nCancelled.")
                default:
                    break
                }
            }
        } catch {
            fail("processing stopped: \(error)")
        }

        if skipped > 0 {
            print("\(skipped) photo(s) couldn't be used.")
        }
        exit(finishedOK ? 0 : 1)
    }
}
