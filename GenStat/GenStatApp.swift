//
//  GenStatApp.swift
//  GenStat
//
//  Created by Tom Hoag on 3/20/26.
//

import SwiftUI

@main
struct GenStatApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        WindowGroup {
            ContentView()
                .task {
                    await requestNotificationPermission()
                }
        }
    }

    private func requestNotificationPermission() async {
        let center = UNUserNotificationCenter.current()
        do {
            let granted = try await center.requestAuthorization(options: [.alert, .sound, .badge])
            if granted {
                await MainActor.run {
                    UIApplication.shared.registerForRemoteNotifications()
                }
            }
        } catch {
            print("Notification authorization failed: \(error)")
        }
    }
}
